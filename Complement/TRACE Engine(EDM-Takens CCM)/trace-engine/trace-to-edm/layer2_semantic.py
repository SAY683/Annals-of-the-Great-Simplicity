"""
Layer 2: 世俗语义流形轴向投影器 v2
====================================
背景PCA + 项目PCA 双层回退策略:
  - 样本 < 10: 使用预计算的背景PCA (全局, 从所有项目数据中训练)
  - 样本 ≥ 10: 切换到项目专属PCA (增量拟合, 每20个样本更新一次)

背景PCA 确保第一条文本就有有意义的 z_pca_1,
不再出现全零列直到积累10条数据。
"""

import pickle
import warnings
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from config import (
    LAYER2_N_COMPONENTS, LAYER2_MIN_SAMPLES_FOR_PCA,
    PCA_CACHE_FILE, VERBOSE, DATA_DIR,
)

warnings.filterwarnings("ignore")

# 全局背景 PCA 缓存位置
BACKGROUND_PCA_FILE = DATA_DIR / "cache" / "_background_pca.pkl"

def _get_bg_pca_path() -> Path:
    """背景 PCA 按模型隔离"""
    try:
        from layer3_sacred import get_active_model
        key = get_active_model()
    except Exception:
        key = "qwen2.5-1.5b"
    return BACKGROUND_PCA_FILE.parent / f"_background_pca_{key}.pkl"


def _get_pca_cache_path() -> Path:
    """获取当前项目的 PCA 缓存路径 (按模型隔离, 与 layer3 共享标识)"""
    try:
        from project_manager import get_project_manager
        base = get_project_manager().current_cache_dir
    except Exception:
        base = PCA_CACHE_FILE.parent if PCA_CACHE_FILE else Path("data/cache")
    # 从 layer3 获取当前模型标识 (同一 Python 进程内)
    try:
        from layer3_sacred import get_active_model
        model_key = get_active_model()
    except Exception:
        model_key = "qwen2.5-1.5b"
    return base / model_key / "_pca_state.pkl"


class SemanticProjector:
    """
    世俗语义流形投影器 (v2 — 背景PCA回退)。

    双层策略:
      Tier 1 (背景PCA): 预计算的全局PCA, 用于样本不足时
      Tier 2 (项目PCA): 项目专属PCA, 样本充足时自动切换
    """

    def __init__(self, sacred_projector=None, hidden_size: int = 1536):
        self.embeddings: List[np.ndarray] = []
        self.pca = None
        self.components: Optional[np.ndarray] = None
        self.explained_variance_ratio: Optional[np.ndarray] = None
        self.sacred_projector = sacred_projector
        self.axis_keywords: List[List[str]] = []
        self._hidden_size = hidden_size  # 期望的向量维度

        # 背景 PCA (用于样本不足时)
        self._bg_pca = None
        self._bg_components: Optional[np.ndarray] = None

        # 尝试加载
        self._load_background_pca()
        self._load_cache()

    # ── 背景 PCA ───────────────────────────────────────

    def _load_background_pca(self):
        """加载全局背景 PCA (按模型隔离)"""
        bg_path = _get_bg_pca_path()
        bg_path.parent.mkdir(parents=True, exist_ok=True)
        if bg_path.exists():
            try:
                with open(bg_path, "rb") as f:
                    state = pickle.load(f)
                self._bg_pca = state.get("pca")
                self._bg_components = state.get("components")
                if VERBOSE and self._bg_components is not None:
                    print(f"[L2] 背景PCA已加载 ({self._bg_components.shape[0]}轴)")
            except Exception as e:
                print(f"[L2] ⚠ 背景PCA加载失败: {e}")

    @staticmethod
    def build_background_pca(embeddings: List[np.ndarray], n_components: int = 3):
        """
        从全局数据构建背景 PCA。

        Args:
            embeddings: 全量 embedding 列表
            n_components: 主轴数量
        """
        from sklearn.decomposition import PCA

        if len(embeddings) < 5:
            print(f"[L2] ⚠ 背景PCA需要至少5个样本 (当前{len(embeddings)})")
            return False

        X = np.stack(embeddings)
        pca = PCA(n_components=min(n_components, X.shape[0], X.shape[1]), random_state=42)
        pca.fit(X)

        state = {
            "pca": pca,
            "components": pca.components_,
            "n_samples": len(embeddings),
            "explained_variance_ratio": pca.explained_variance_ratio_,
        }

        bg_path = _get_bg_pca_path()
        bg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(bg_path, "wb") as f:
            pickle.dump(state, f)

        if VERBOSE:
            print(f"[L2] 背景PCA已构建: {len(embeddings)}样本, "
                  f"{pca.n_components_}轴, "
                  f"累计方差={np.sum(pca.explained_variance_ratio_):.3f}")

        return True

    # ── 项目 PCA 缓存 ──────────────────────────────────

    def _load_cache(self):
        cache_path = _get_pca_cache_path()
        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f:
                    state = pickle.load(f)
                self.pca = state.get("pca")
                self.embeddings = state.get("embeddings", [])
                self.components = state.get("components")
                self.explained_variance_ratio = state.get("explained_variance_ratio")
                self.axis_keywords = state.get("axis_keywords", [])
                if VERBOSE:
                    print(f"[L2] 项目PCA已加载 (已累积 {len(self.embeddings)} 篇)")
            except Exception as e:
                print(f"[L2] ⚠ PCA缓存恢复失败: {e}")
                self.pca = None

    def _save_cache(self):
        cache_path = _get_pca_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "pca": self.pca, "embeddings": self.embeddings,
            "components": self.components,
            "explained_variance_ratio": self.explained_variance_ratio,
            "axis_keywords": self.axis_keywords,
        }
        with open(cache_path, "wb") as f:
            pickle.dump(state, f)

    # ── 核心逻辑 ───────────────────────────────────────

    def add_embedding(self, embedding: np.ndarray):
        self.embeddings.append(embedding)
        n = len(self.embeddings)

        if n < LAYER2_MIN_SAMPLES_FOR_PCA:
            return
        if n == LAYER2_MIN_SAMPLES_FOR_PCA:
            self._refit_pca()
            return

        interval = 5 if n <= 20 else 20
        if n % interval == 0:
            self._refit_pca()

    def _refit_pca(self):
        from sklearn.decomposition import PCA
        X = np.stack(self.embeddings)
        n_components = min(LAYER2_N_COMPONENTS, X.shape[0], X.shape[1])
        self.pca = PCA(n_components=n_components, random_state=42)
        self.pca.fit(X)
        self.components = self.pca.components_
        self.explained_variance_ratio = self.pca.explained_variance_ratio_
        if VERBOSE:
            print(f"[L2] 项目PCA拟合: {len(self.embeddings)}样本, "
                  f"{n_components}轴, 方差={np.sum(self.explained_variance_ratio):.3f}")
        self._save_cache()

    def _get_active_components(self) -> Optional[np.ndarray]:
        """
        获取当前有效的 PCA 主轴。
        优先级: 项目PCA > 背景PCA > None
        """
        if self.components is not None:
            return self.components
        if self._bg_components is not None:
            return self._bg_components
        return None

    def project(self, embedding: np.ndarray) -> Dict[str, float]:
        result = {}

        components = self._get_active_components()

        if components is None:
            for i in range(LAYER2_N_COMPONENTS):
                result[f"z_pca_{i+1}"] = 0.0
            result["secular_entropy"] = 0.0
            return result

        n_axes = components.shape[0]
        for i in range(n_axes):
            result[f"z_pca_{i+1}"] = float(np.dot(embedding, components[i]))
        for i in range(n_axes, LAYER2_N_COMPONENTS):
            result[f"z_pca_{i+1}"] = 0.0

        # 世俗熵
        projections = [abs(result[f"z_pca_{i+1}"]) for i in range(n_axes)]
        total = sum(projections) + 1e-10
        probs = [p / total for p in projections]
        entropy = -sum(p * np.log(p + 1e-10) for p in probs)
        max_entropy = np.log(len(probs)) if len(probs) > 1 else 1.0
        result["secular_entropy"] = entropy / max_entropy if max_entropy > 0 else 0.0

        return result

    def add_and_project(self, embedding: np.ndarray) -> Dict[str, float]:
        self.add_embedding(embedding)
        return self.project(embedding)

    def get_pca_info(self) -> Dict:
        if self.pca is None:
            info = {"status": "not_fitted", "n_samples": len(self.embeddings)}
            if self._bg_pca is not None:
                info["fallback"] = "background_pca"
                info["bg_n_samples"] = getattr(self._bg_pca, 'n_samples_', 0)
            return info
        return {
            "status": "fitted",
            "n_samples": len(self.embeddings),
            "n_components": self.pca.n_components_,
            "explained_variance_ratio": self.explained_variance_ratio.tolist(),
            "cumulative_variance": float(np.sum(self.explained_variance_ratio)),
        }

    @property
    def n_samples(self) -> int:
        return len(self.embeddings)

    @property
    def is_ready(self) -> bool:
        return self.pca is not None or self._bg_pca is not None


# ── 构建背景PCA工具 ────────────────────────────────────────

def build_background_pca_from_all_projects():
    """
    从八正道神圣向量构建背景 PCA。

    使用8个经书向量 (1536维) 做PCA, 提取3个主轴作为初始背景。
    这些主轴捕获了神圣语义空间中的真实方向——比随机向量有意义得多。
    当项目积累≥10个样本后, 项目专属PCA自动接管。
    """
    from layer3_sacred import SacredProjector

    # 加载神圣向量
    proj = SacredProjector()
    proj.load_sacred_texts()

    sacred_embs = []
    for name, vec in proj.sacred_vectors.items():
        sacred_embs.append(vec)

    if len(sacred_embs) >= 5:
        SemanticProjector.build_background_pca(sacred_embs)
        if VERBOSE:
            print(f"[L2] 背景PCA: 基于{len(sacred_embs)}个神圣向量构建")
    else:
        # 最终回退: 随机向量 (保证不崩溃)
        print(f"[L2] ⚠ 神圣向量不足({len(sacred_embs)}), 使用随机背景")
        rng = np.random.RandomState(42)
        fake = [rng.randn(1536).astype(np.float32) for _ in range(20)]
        for v in fake: v /= np.linalg.norm(v)
        SemanticProjector.build_background_pca(fake)


# ── 自检 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--build-bg":
        print("构建背景PCA...")
        build_background_pca_from_all_projects()
    else:
        print("Layer 2 自检")
        proj = SemanticProjector()
        print(f"  就绪: {proj.is_ready}")
        print(f"  背景PCA: {proj._bg_components is not None}")
        print(f"  项目PCA: {proj.pca is not None}")
