"""
Layer 3: 八正道神圣坐标轴投影器 (Sacred Axis Projection)
==========================================================
使用零样本线性探针对齐 (Zero-Shot Cosine-Similarity Probing),
将任何世俗文本投影到八个不变的神圣坐标轴上。

物理机制:
  1. 用 Qwen2.5-1.5B 对八本私域圣经的核心定义文本进行编码
     → 得到 8 个不变的方向向量 w_1, w_2, ..., w_8 ∈ R^1536
  2. 对输入世俗文本，提取最后一层隐藏状态 h_x ∈ R^1536
  3. 计算余弦相似度: s_j = (w_j · h_x) / (|w_j| |h_x|)
     → 得到 8 个实数坐标: [z_福音, z_吉祥, ..., z_觉爱]

关键理解:
  - 大多数世俗文本的投影值接近 0（正交）——这不是失败，是测量
  - "零" 意味着这段文字在本体论上是空的
  - 真正有价值的是 z 值的一阶差分 (Δz/Δt) 和二阶差分 (Δ²z/Δt²)
  - 这些差分信号在 pyEDM 中比绝对投影值更有动力学意义

用法:
  from layer3_sacred import SacredProjector
  projector = SacredProjector()
  coords = projector.project("一篇世俗文本...")
  # → {"z_福音": 0.03, "z_吉祥": 0.01, ...}
  derivatives = projector.compute_derivatives(history_of_coords)
  # → {"dz_存在": +0.005, "d2z_存在": -0.002, ...}
"""

import os
import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
# torch 改为延迟导入 (在 _get_device / _load_model / encode_text 内部),
# 以便在未安装 torch 的环境中仍可加载本模块的元数据函数
# (list_models / get_active_model / set_active_model), 让 /api/models 端点
# 能正常返回模型列表, 而不会因 ModuleNotFoundError 导致前端显示"无可用模型"。

from config import (
    QWEN_MODEL_PATH, QWEN_MODEL_PATH_3B,
    SHEHUI_MODEL_PATH, SHENJI_MODEL_PATH,
    SACRED_TEXTS_DIR, SACRED_BOOKS,
    CACHE_DIR, VERBOSE,
)

warnings.filterwarnings("ignore")


def _get_sacred_cache_dir() -> Path:
    """获取当前项目的经书向量缓存目录 (按模型隔离)"""
    try:
        from project_manager import get_project_manager
        base = get_project_manager().current_cache_dir
    except Exception:
        base = CACHE_DIR
    # 按模型名隔离缓存 (1536 vs 2048 维)
    return base / _ACTIVE_MODEL

# ── 模型注册表 ──────────────────────────────────────────────
MODEL_REGISTRY = {
    "qwen2.5-1.5b": {
        "name": "Qwen2.5-1.5B-Instruct",
        "path": str(QWEN_MODEL_PATH),
        "hidden_size": 1536, "num_layers": 28, "middle_layer": 14,
        "description": "1.5B 轻量 (~3GB显存)", "quantize": False,
    },
}
# 3B 模型直接从 config.QWEN_MODEL_PATH_3B 读取独立路径
# （旧实现 `str(QWEN_MODEL_PATH).replace("1.5B", "3B")` 脆弱，已废弃）
MODEL_REGISTRY["qwen2.5-3b"] = {
    "name": "Qwen2.5-3B-Instruct", "path": str(QWEN_MODEL_PATH_3B),
    "hidden_size": 2048, "num_layers": 36, "middle_layer": 18,
    "description": "3B 精度 (4-bit量化, ~2.8GB显存)", "quantize": True,
}

# TRACE LLaMA 模型：仅注册供下拉展示，实际加载仍走 Qwen 路径
MODEL_REGISTRY["shehui-llama"] = {
    "name": "shehui-llama (TRACE)", "path": str(SHEHUI_MODEL_PATH),
    "hidden_size": 384, "num_layers": 28, "middle_layer": 14,
    "description": "TRACE LLaMA 社会模型 (仅展示)", "quantize": False,
    "trace_model": True,
}
MODEL_REGISTRY["shenji-llama"] = {
    "name": "shenji-llama (TRACE)", "path": str(SHENJI_MODEL_PATH),
    "hidden_size": 896, "num_layers": 36, "middle_layer": 18,
    "description": "TRACE LLaMA 审计模型 (仅展示)", "quantize": False,
    "trace_model": True,
}

_ACTIVE_MODEL = "qwen2.5-1.5b"

# 持久化: 将模型选择写入 cache 目录, 跨进程保持
def _model_config_path():
    try:
        from config import CACHE_DIR
        return CACHE_DIR / "_active_model.txt"
    except:
        from pathlib import Path
        return Path("data/cache/_active_model.txt")

def _load_model_config():
    global _ACTIVE_MODEL
    p = _model_config_path()
    if p.exists():
        try:
            with open(p, 'r') as f:
                saved = f.read().strip()
            if saved in MODEL_REGISTRY:
                _ACTIVE_MODEL = saved
        except: pass

def _save_model_config():
    p = _model_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w') as f:
        f.write(_ACTIVE_MODEL)

_load_model_config()  # 启动时恢复上次的选择

def get_active_model(): return _ACTIVE_MODEL
def set_active_model(key):
    global _ACTIVE_MODEL, _MODEL, _TOKENIZER, _DEVICE, _SACRED_VECTORS
    if key in MODEL_REGISTRY:
        _ACTIVE_MODEL = key
        _save_model_config()   # 持久化到磁盘
        _MODEL = None; _TOKENIZER = None
        _SACRED_VECTORS = None  # Q9 P1-15 修复：切换模型时重置八正道向量缓存，防止 1.5B↔3B 维度不匹配
        return True
    return False
def list_models(): return [{"key": k, **v} for k, v in MODEL_REGISTRY.items()]

# ── 全局模型缓存 ────────────────────────────────────────────
_MODEL = None
_TOKENIZER = None
_DEVICE = None
_SACRED_VECTORS: Optional[Dict[str, np.ndarray]] = None  # 缓存的八正道方向向量


def _get_device() -> str:
    """检测可用设备"""
    import torch
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_model():
    """延迟加载 Qwen 模型 (单例模式)"""
    global _MODEL, _TOKENIZER, _DEVICE

    if _MODEL is not None:
        return _MODEL, _TOKENIZER, _DEVICE

    import torch
    from transformers import AutoModel, AutoTokenizer

    _DEVICE = _get_device()
    cfg = MODEL_REGISTRY.get(_ACTIVE_MODEL, MODEL_REGISTRY["qwen2.5-1.5b"])
    model_path = cfg["path"]
    use_quantize = cfg.get("quantize", False)

    if VERBOSE:
        print(f"[L3] 加载 {cfg['name']} (device={_DEVICE}, 4bit={use_quantize})")

    _TOKENIZER = AutoTokenizer.from_pretrained(
        model_path, trust_remote_code=True, padding_side="left"
    )
    if _TOKENIZER.pad_token is None:
        _TOKENIZER.pad_token = _TOKENIZER.eos_token

    if use_quantize and _DEVICE == "cuda":
        try:
            from transformers import BitsAndBytesConfig
            _MODEL = AutoModel.from_pretrained(
                model_path, trust_remote_code=True,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16,
                ),
                attn_implementation="sdpa",
                device_map="auto",
            )
        except Exception as e:
            print(f"[L3] 4-bit量化失败({e}), 回退FP16")
            _MODEL = AutoModel.from_pretrained(
                model_path, trust_remote_code=True,
                dtype=torch.float16, device_map="auto",
            )
    else:
        _MODEL = AutoModel.from_pretrained(
            model_path, trust_remote_code=True,
            dtype=torch.float16 if _DEVICE == "cuda" else torch.float32,
        ).to(_DEVICE)
    _MODEL.eval()

    if VERBOSE:
        print(f"[L3] 模型加载完成 ✓ (hidden_size={_MODEL.config.hidden_size})")

    return _MODEL, _TOKENIZER, _DEVICE


def encode_text(text: str) -> np.ndarray:
    """
    用 Qwen 编码文本，返回 mean-pooled 隐状态向量。

    Args:
        text: 输入文本 (任意长度)

    Returns:
        np.ndarray shape=(hidden_size,), 已 L2 归一化
    """
    model, tokenizer, device = _load_model()
    import torch
    cfg = MODEL_REGISTRY.get(_ACTIVE_MODEL, MODEL_REGISTRY["qwen2.5-1.5b"])
    middle_layer = cfg.get("middle_layer", 14)
    max_len = model.config.max_position_embeddings

    # ── 滑动窗口分块 (chunk_size=256, overlap=64) ──────────
    tokens = tokenizer.encode(text, add_special_tokens=False)
    chunk_size = 256
    overlap = 64
    step = chunk_size - overlap
    chunk_embeddings = []

    model.eval()
    with torch.no_grad():
        for start in range(0, len(tokens), step):
            chunk = tokens[start:start + chunk_size]
            if len(chunk) < 10:
                continue

            inputs = torch.tensor([chunk], dtype=torch.long).to(device)
            # 提取中层 hidden states (避免顶层 Instruct 对齐污染)
            outputs = model(inputs, output_hidden_states=True)
            hidden = outputs.hidden_states[middle_layer]  # [1, seq, hidden_size]

            # Mean pooling
            pooled = hidden.float().mean(dim=1)  # [1, hidden_size]
            vec = pooled.cpu().numpy().squeeze().astype(np.float64)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            chunk_embeddings.append(vec)

            del inputs, outputs, hidden, pooled
            # 每10块清理一次VRAM
            if len(chunk_embeddings) % 10 == 0:
                import gc
                gc.collect()
                torch.cuda.empty_cache()

    # ── 聚合: SVD提取第一右奇异向量 > mean-pooling ──────
    if len(chunk_embeddings) >= 2:
        M = np.stack(chunk_embeddings)  # [n_chunks, hidden_size]
        try:
            U, S, Vt = np.linalg.svd(M, full_matrices=False)
            vec = Vt[0].astype(np.float64)  # 第一右奇异向量
        except np.linalg.LinAlgError:
            vec = np.mean(M, axis=0).astype(np.float64)
    elif len(chunk_embeddings) == 1:
        vec = chunk_embeddings[0]
    else:
        vec = np.zeros(cfg["hidden_size"], dtype=np.float64)

    import gc
    gc.collect()
    torch.cuda.empty_cache()

    # NaN 安全检查
    if np.any(np.isnan(vec)) or np.all(vec == 0):
        # 回退: 使用确定性哈希替代 Python 内建 hash()
        # (Python hash 在进程间随机化, 导致同一文本产生不同向量)
        import hashlib
        seed = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)
        rng = np.random.RandomState(seed)
        vec = rng.randn(len(vec)).astype(np.float64)

    # L2 归一化
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return vec


class SacredProjector:
    """
    八正道神圣坐标轴投影器。

    加载八本私域圣经的定义文本，编码为八个不变的方向向量，
    然后将任何输入文本投影到这八个轴上。

    Attributes:
        sacred_vectors: Dict[str, np.ndarray] — 八本经书的归一化方向向量
        book_names: List[str] — 经书简称列表
    """

    def __init__(self):
        self.sacred_vectors: Dict[str, np.ndarray] = {}
        self.book_names: List[str] = []
        self._loaded = False

    def load_sacred_texts(self) -> bool:
        """
        从 sacred_texts/ 目录加载并编码八本经书。

        Returns:
            bool: 是否成功加载了所有八本经书
        """
        if self._loaded:
            return True

        # 尝试从缓存加载
        cache_dir = _get_sacred_cache_dir()
        cache_file = cache_dir / "_sacred_vectors.npy"
        cache_meta = cache_dir / "_sacred_vectors_meta.json"

        if cache_file.exists() and cache_meta.exists():
            if VERBOSE:
                print("[L3] 从缓存加载神圣向量...")
            with open(cache_meta, "r", encoding="utf-8") as f:
                meta = json.load(f)
            vectors = np.load(cache_file)
            for i, name in enumerate(meta["book_names"]):
                self.sacred_vectors[name] = vectors[i]
            self.book_names = meta["book_names"]
            self._loaded = True
            if VERBOSE:
                print(f"[L3] 已加载 {len(self.sacred_vectors)} 个缓存神圣向量 ✓")
            return True

        # 从文本文件编码
        if VERBOSE:
            print("[L3] 编码八正道神圣文本...")

        missing = []
        for short_name, full_name, filename in SACRED_BOOKS:
            filepath = SACRED_TEXTS_DIR / filename
            if not filepath.exists():
                missing.append((short_name, filename))
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    sacred_text = f.read().strip()

                if not sacred_text:
                    missing.append((short_name, filename))
                    continue

                vec = encode_text(sacred_text)
                self.sacred_vectors[short_name] = vec
                self.book_names.append(short_name)

                if VERBOSE:
                    print(f"  ✓ {short_name}({full_name}): |w|={np.linalg.norm(vec):.4f}")

            except Exception as e:
                print(f"[L3] ⚠ 编码 {short_name}({full_name}) 失败: {e}")
                missing.append((short_name, filename))

        if missing:
            print(f"[L3] ⚠ 以下经书文本缺失或为空，已跳过: {missing}")
            print(f"[L3]    请在 {SACRED_TEXTS_DIR}/ 下放置对应的 .txt 文件")

        if len(self.sacred_vectors) == 0:
            print("[L3] ❌ 没有加载到任何有效的经书文本。层 3 将生成零向量。")
            self._loaded = True
            return False

        # 缓存
        self._save_cache()
        self._loaded = True

        if VERBOSE:
            print(f"[L3] 编码完成: {len(self.sacred_vectors)}/{len(SACRED_BOOKS)} 本经书就绪 ✓")

        return len(missing) == 0

    def _save_cache(self):
        """将编码后的神圣向量保存到项目级缓存 (仅当所有向量有效时)"""
        # 验证所有向量有效
        for name, vec in self.sacred_vectors.items():
            if np.any(np.isnan(vec)) or np.all(vec == 0):
                print(f"[L3] ⚠ 向量 {name} 无效 (NaN/零), 跳过缓存")
                return

        cache_dir = _get_sacred_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        vectors = np.stack([self.sacred_vectors[name] for name in self.book_names])
        np.save(cache_dir / "_sacred_vectors.npy", vectors)
        with open(cache_dir / "_sacred_vectors_meta.json", "w", encoding="utf-8") as f:
            json.dump({"book_names": self.book_names}, f, ensure_ascii=False)
        if VERBOSE:
            print(f"[L3] 神圣向量已缓存 ✓")

    def project(self, text: str) -> Dict[str, float]:
        """
        将输入文本投影到八正道神圣坐标轴上。

        Args:
            text: 输入文本

        Returns:
            Dict[str, float]: {"z_福音": 0.03, "z_吉祥": 0.01, ...}
                             值域 [-1, 1], 0 表示完全正交
        """
        coords, _ = self._project_with_vector(text)
        return coords

    def _project_with_vector(self, text: str) -> Tuple[Dict[str, float], np.ndarray]:
        """
        将输入文本投影到八正道神圣坐标轴上，并返回原始文本嵌入向量。

        Returns:
            (coords, h_x): coords 为投影坐标字典，h_x 为 L2 归一化的文本嵌入向量。
                           h_x 用于 project_with_orthogonalization 的数学正确重投影。
        """
        if not self._loaded:
            self.load_sacred_texts()

        if not self.sacred_vectors:
            # 没有加载到经书 → 返回零
            dim = MODEL_REGISTRY.get(_ACTIVE_MODEL, MODEL_REGISTRY["qwen2.5-1.5b"])["hidden_size"]
            return {f"z_{name}": 0.0 for name, _, _ in SACRED_BOOKS}, np.zeros(dim, dtype=np.float64)

        # 编码输入文本
        h_x = encode_text(text)  # 已 L2 归一化

        # 计算余弦相似度
        coords = {}
        for name, _, _ in SACRED_BOOKS:
            if name in self.sacred_vectors:
                w = self.sacred_vectors[name]
                # 两个向量都已归一化，直接点积 = cos sim
                sim = float(np.dot(w, h_x))
                coords[f"z_{name}"] = sim
            else:
                coords[f"z_{name}"] = 0.0

        return coords, h_x

    def compute_derivatives(
        self,
        history: List[Dict[str, float]],
        timestamps: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        从历史投影值计算一阶和二阶差分。

        Args:
            history: 按时间排序的投影字典列表，至少需要 2 个点
            timestamps: 可选的 ISO/字符串时间戳列表，长度需与 history 一致。
                        若提供且可解析为 datetime，差分会按 Δt（秒）归一化，
                        以支持非均匀时间采样；否则退化为等间隔差分。

        Returns:
            包含 dz_* 和 d2z_* 的字典
        """
        from datetime import datetime

        derivatives = {}

        if len(history) < 2:
            return derivatives

        # 解析时间戳（如果提供）
        use_time = False
        dt_secs = None
        if timestamps is not None and len(timestamps) == len(history):
            parsed = []
            for ts in timestamps:
                try:
                    # 支持 ISO 格式（含空格）和纯日期
                    if isinstance(ts, str):
                        ts_norm = ts.replace(" ", "T")
                        parsed.append(datetime.fromisoformat(ts_norm))
                    else:
                        parsed.append(datetime.fromisoformat(str(ts)))
                except Exception:
                    parsed = []
                    break
            if len(parsed) == len(history):
                dt1 = (parsed[-1] - parsed[-2]).total_seconds()
                use_time = dt1 > 1e-6
                if use_time:
                    dt_secs = {"latest": dt1}
                    if len(history) >= 3:
                        dt2 = (parsed[-2] - parsed[-3]).total_seconds()
                        if dt2 > 1e-6:
                            dt_secs["prev"] = dt2

        # 一阶差分 Δz/Δt（非均匀时间采样时归一化）
        latest = history[-1]
        prev = history[-2]
        dt1 = dt_secs["latest"] if use_time else 1.0
        for key in latest:
            if key.startswith("z_"):
                d_key = key.replace("z_", "dz_")
                derivatives[d_key] = (latest[key] - prev[key]) / dt1

        # 二阶差分 Δ²z/Δt²
        if len(history) >= 3:
            prev2 = history[-3]
            dt2 = dt_secs.get("prev", 1.0) if use_time else 1.0
            for key in latest:
                if key.startswith("z_"):
                    d2_key = key.replace("z_", "d2z_")
                    dz_now = (latest[key] - prev[key]) / dt1
                    dz_prev = (prev[key] - prev2[key]) / dt2
                    # 二阶差分对平均 Δt 归一化
                    avg_dt = (dt1 + dt2) / 2.0 if use_time else 1.0
                    derivatives[d2_key] = (dz_now - dz_prev) / avg_dt

        return derivatives

    def get_orthogonality_matrix(self) -> Optional[np.ndarray]:
        """
        计算八正道向量之间的正交性矩阵。
        理想情况下非对角元素应接近 0（各轴独立）。

        Returns:
            8x8 余弦相似度矩阵
        """
        if not self.sacred_vectors:
            return None

        names = [name for name, _, _ in SACRED_BOOKS if name in self.sacred_vectors]
        n = len(names)
        matrix = np.zeros((n, n))

        for i, ni in enumerate(names):
            for j, nj in enumerate(names):
                matrix[i, j] = float(np.dot(
                    self.sacred_vectors[ni],
                    self.sacred_vectors[nj]
                ))

        return matrix

    def get_orthogonality_report(self) -> dict:
        """
        元审计 P1 修缮: 让正交性矩阵可被管线消费
        之前 get_orthogonality_matrix 仅用于自检，未被管线消费
        现返回结构化报告，供 csv_builder/bridge 写入诊断字段

        Returns:
            {
                "matrix": [[8x8]],
                "names": [...],
                "max_off_diagonal": float,  # 最大非对角值（越低越好）
                "mean_off_diagonal": float,  # 平均非对角值
                "axis_independence": "good"|"moderate"|"poor",
                "degenerate_axes": [...],   # 与其他轴余弦>0.9 的"退化的轴"
            }
        """
        matrix = self.get_orthogonality_matrix()
        if matrix is None:
            return {"available": False}

        names = [name for name, _, _ in SACRED_BOOKS if name in self.sacred_vectors]
        n = len(names)
        off_diag = []
        degenerate = set()

        for i in range(n):
            for j in range(n):
                if i != j:
                    off_diag.append(abs(matrix[i, j]))
                    if abs(matrix[i, j]) > 0.9:
                        degenerate.add(names[i])
                        degenerate.add(names[j])

        max_off = max(off_diag) if off_diag else 0.0
        mean_off = float(np.mean(off_diag)) if off_diag else 0.0

        # 数学严谨性: 报告原始神圣向量矩阵 W 的 Gram 矩阵与单位矩阵的 Frobenius 距离
        # Q9 算法审视修复: 原代码计算 Q^T Q - I，但 QR 分解的 Q 本身就是正交的
        # (Q^T Q = I 严格成立，仅数值精度误差 ~1e-15)，导致 frobenius_distance 几乎
        # 总是 ~0，完全无诊断价值。应测量原始 W 的不正交程度。
        try:
            W = np.stack([self.sacred_vectors[n] for n in names], axis=1)
            # 列归一化后再算 Gram 矩阵，消除向量长度差异的影响
            W_norms = np.linalg.norm(W, axis=0, keepdims=True)
            W_norms[W_norms == 0] = 1.0  # 防止除零
            W_normalized = W / W_norms
            gram = W_normalized.T @ W_normalized
            frobenius_distance = float(np.linalg.norm(gram - np.eye(n), ord='fro'))
        except Exception:
            frobenius_distance = None

        if max_off < 0.5:
            independence = "good"
        elif max_off < 0.9:
            independence = "moderate"
        else:
            independence = "poor"

        return {
            "available": True,
            "matrix": matrix.tolist(),
            "names": names,
            "max_off_diagonal": float(max_off),
            "mean_off_diagonal": float(mean_off),
            "frobenius_distance": frobenius_distance,
            "axis_independence": independence,
            "degenerate_axes": sorted(degenerate),
        }

    def project_with_orthogonalization(self, text: str, method: str = "gram_schmidt") -> dict:
        """
        元审计 P1 修缮: 八正道区分度增强
        之前 8 个 z 值在 SEED 项目实际数据中集中在 [-0.72, -0.67]，区分度不足
        现增加 Gram-Schmidt 正交化后处理，让 8 轴在投影空间中真正独立

        method:
            "gram_schmidt" - 经典 Gram-Schmidt（数值稳定性一般）
            "modified_gs"  - 修正 Gram-Schmidt（数值稳定性更好，推荐）
            "qr"           - QR 分解（最稳定，等价于 modified_gs）

        Returns:
            {
                "z_福音": ..., ..., "z_觉爱": ...,  # 正交化后的投影值
                "_orthogonality_report": {...},     # 正交性报告
                "_method": method,
            }
        """
        # 1. 先做常规投影，同时保留原始文本嵌入 h_x
        coords, h_x = self._project_with_vector(text)
        if not coords:
            return {}

        # 2. 获取 8 个神圣向量，构造矩阵 W (d x 8)
        names = [name for name, _, _ in SACRED_BOOKS if name in self.sacred_vectors]
        if len(names) < 2:
            return coords  # 无法正交化

        W = np.stack([self.sacred_vectors[n] for n in names], axis=1)  # (d, 8)

        # 3. 对 W 做正交化（让 8 个基向量彼此正交）
        if method == "gram_schmidt":
            Q = self._gram_schmidt(W)
        elif method == "modified_gs":
            Q = self._modified_gram_schmidt(W)
        elif method == "qr":
            Q, _ = np.linalg.qr(W)
        else:
            raise ValueError(f"unknown orthogonalization method: {method}")

        # 4. 用正交化后的 Q 重新投影
        # 数学正确性: Q 的列张成与 W 相同的子空间，但彼此正交归一化。
        # 原投影 z_i = w_i · h_x 因 W 列不正交而存在轴间耦合。
        # 正交化后新坐标应为 z'_i = q_i · h_x，直接对真实文本嵌入 h_x 投影。
        # 注意: 绝不能用 W @ coords 反推 h_x，因为 W 非正交时该近似不是正交投影，
        # 会导致二次误差。我们直接复用 _project_with_vector 返回的 h_x。
        new_coords_vec = Q.T @ h_x

        # 5. 构造新的 coords dict
        new_coords = {f"z_{names[i]}": float(new_coords_vec[i]) for i in range(len(names))}
        new_coords["_orthogonality_report"] = self.get_orthogonality_report()
        new_coords["_method"] = method
        return new_coords

    @staticmethod
    def _gram_schmidt(W: np.ndarray) -> np.ndarray:
        """经典 Gram-Schmidt 正交化"""
        Q = W.copy().astype(np.float64)
        for i in range(Q.shape[1]):
            for j in range(i):
                Q[:, i] -= np.dot(Q[:, j], Q[:, i]) * Q[:, j]
            norm = np.linalg.norm(Q[:, i])
            if norm > 1e-10:
                Q[:, i] /= norm
            else:
                # 退化的轴，保留原方向（避免除零）
                Q[:, i] = W[:, i] / (np.linalg.norm(W[:, i]) + 1e-10)
        return Q

    @staticmethod
    def _modified_gram_schmidt(W: np.ndarray) -> np.ndarray:
        """修正 Gram-Schmidt 正交化（数值稳定性更好）"""
        Q = W.copy().astype(np.float64)
        for i in range(Q.shape[1]):
            norm = np.linalg.norm(Q[:, i])
            if norm > 1e-10:
                Q[:, i] /= norm
            for j in range(i + 1, Q.shape[1]):
                Q[:, j] -= np.dot(Q[:, i], Q[:, j]) * Q[:, i]
        return Q


# ── 自检 ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("Layer 3 自检: 八正道神圣坐标轴投影器")
    print("=" * 60)

    projector = SacredProjector()
    all_loaded = projector.load_sacred_texts()

    if not all_loaded:
        print("\n⚠ 部分经书文本未找到。请在 sacred_texts/ 下放置 .txt 文件。")
        print("  每个文件应包含该经书的核心定义文本。\n")

    # 测试投影
    test_texts = [
        "算法推荐系统通过持续分析用户行为数据，精准推送用户感兴趣的内容。",
        "存在本身是自足的，真理不需要外在的证明。爱是连接有限与无限的桥梁。",
    ]

    for text in test_texts:
        coords = projector.project(text)
        print(f"\n输入: {text[:60]}...")
        for key, val in sorted(coords.items()):
            bar = "█" * max(0, int(abs(val) * 50))
            sign = "+" if val >= 0 else "-"
            if abs(val) < 0.001:
                bar = "· (正交)"
            print(f"  {key:12s} = {val:+.6f}  {sign}{bar}")

    # 正交性检查
    ortho = projector.get_orthogonality_matrix()
    if ortho is not None:
        print("\n--- 八正道轴间正交性 ---")
        names = [n for n, _, _ in SACRED_BOOKS if n in projector.sacred_vectors]
        print(f"  {'':8s}", end="")
        for n in names:
            print(f"{n:>8s}", end="")
        print()
        for i, ni in enumerate(names):
            print(f"  {ni:8s}", end="")
            for j, nj in enumerate(names):
                marker = "*" if i == j else " "
                print(f"{ortho[i,j]:8.4f}{marker}", end="")
            print()
        print("  (* 对角线 = 自相似度, 非对角 < 0.5 = 轴间独立性好)")

    print("\nLayer 3 自检完成 ✓")
