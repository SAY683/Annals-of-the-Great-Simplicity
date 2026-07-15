#!/usr/bin/env python3
"""
TRACE Engine Web — LLaMA Resident Worker
=========================================
常驻 Python Worker，加载训练好的 Shehui-LLaMA / Shenji-LLaMA 模型，
为 trace-engine-web 的 SUPER 模式提供真正的 token-level TRACE 因果发现。

通信协议:
  - 从 stdin 读取 JSON Lines，每行一个任务
  - 向 stdout 输出 JSON Lines（stage/log/result/error）

输入任务格式:
  {
    "id": "uuid",
    "text": "输入文本",
    "model": "shehui-llama" | "shenji-llama",  // 默认 shehui-llama
    "mode": "super",
    "config": {...}  // 桥接参数
  }

输出事件格式:
  {"type": "stage", "stage": "load", "message": "...", "progress": 0.0}
  {"type": "log", "level": "info", "message": "..."}
  {"type": "result", "payload": {...}}
  {"type": "error", "message": "..."}
"""
import gc
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

warnings.filterwarnings('ignore')

# 大模型（469M+）在 Windows 小显存上容易因显存碎片 OOM，开启 expandable_segments 缓解
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')

# ══════════════════════════════════════════════════════════════════════
# 路径解析：从 trace-engine-web 定位到 trace-engine skill 目录
# ══════════════════════════════════════════════════════════════════════
WORKER_DIR = Path(__file__).resolve().parent
# 成品/开发目录通用：trace-engine-web 与 trace-engine 处于同一父目录
PRODUCT_ENGINE = WORKER_DIR.parent / 'trace-engine'
SKILL_DIR = PRODUCT_ENGINE / 'examples' / 'counterfactual_hybrid'

# 开发目录：从 .skills/trace-engine-web 向上找到 .skills/trace-engine
DEV_SKILL = WORKER_DIR.parent.parent / '.skills' / 'trace-engine' / 'examples' / 'counterfactual_hybrid'

if SKILL_DIR.exists():
    TRACE_ENGINE_DIR = PRODUCT_ENGINE
    SKILL_DIR = SKILL_DIR
elif DEV_SKILL.exists():
    TRACE_ENGINE_DIR = DEV_SKILL.parent.parent
    SKILL_DIR = DEV_SKILL
else:
    TRACE_ENGINE_DIR = PRODUCT_ENGINE
    SKILL_DIR = PRODUCT_ENGINE / 'examples' / 'counterfactual_hybrid'

# 不强制设置 TRACE_ROOT：project_paths / _config 会根据 SKILL_DIR 自动探测
#   - 开发布局 -> <project_root>/TRACE
#   - 层级成品布局 -> <product>/trace-engine
# 这样 dev 与 product 两种布局都能正确找到 models/ 目录。

sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(TRACE_ENGINE_DIR))

# 现在可以导入 skill 模块
import numpy as np
import sentencepiece as spm
import torch
import torch.nn.functional as F
from transformers import LlamaForCausalLM

from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter
from dowhy_auditor import DoWhyAuditor
from presets import load_presets
from project_paths import resolve_paths
from six_warriors import assemble_all_six


# ══════════════════════════════════════════════════════════════════════
# 日志/输出辅助
# ══════════════════════════════════════════════════════════════════════
def emit(obj: dict):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def log(level: str, message: str):
    emit({"type": "log", "level": level, "message": message})


def stats(processed: int, total: int, elapsed: float):
    """ emit TRACE 实时速率与 ETA 统计。"""
    rate = processed / elapsed if elapsed > 0 else 0.0
    remaining = max(0, (total - processed) / rate) if rate > 0 else 0.0
    progress = processed / total if total > 0 else 0.0
    emit({
        "type": "stats",
        "stats": {
            "processed_pairs": processed,
            "total_pairs": total,
            "rate": round(rate, 2),
            "elapsed_seconds": round(elapsed, 1),
            "remaining_seconds": round(remaining, 1),
            "progress": round(progress, 2),
        },
    })


def stage(name: str, message: str, progress: float = None):
    obj = {"type": "stage", "stage": name, "message": message}
    if progress is not None:
        obj["progress"] = round(progress, 2)
    emit(obj)


def error(message: str):
    emit({"type": "error", "message": message})


def _estimate_trace_pairs(segments: List[List[int]], window: int) -> int:
    """估算 TRACE 阶段需要计算的总 token 对数（用于进度与耗时预估）。"""
    total = 0
    for seq in segments:
        L = len(seq)
        # 对每个 ti，候选历史长度 = min(window, ti)
        total += sum(min(window, ti) for ti in range(1, L))
    return max(1, total)


def _check_vram_budget(n_params_m: float, device: torch.device):
    """V4 模型 VRAM 预算检查：469M 参数在 FP32 下约需 3.5GB+，显存不足时给出警告。"""
    if device.type != 'cuda':
        return
    try:
        free_gb = torch.cuda.mem_get_info()[0] / 1e9
        # 469M 参数 FP32 ≈ 1.88GB 权重 + 激活/梯度/碎片 ≈ 3.0-3.5GB 安全余量
        required_gb = 3.0 if n_params_m and n_params_m > 200 else 1.5
        if free_gb < required_gb:
            log('warn', f'VRAM 预算紧张: 空闲 {free_gb:.1f}GB < 建议 {required_gb:.1f}GB')
            log('warn', '建议: 关闭其它 GPU 程序、设置 TRACE_MODEL_DTYPE=fp16，或减少 window_size/max_segments')
        else:
            log('info', f'VRAM 预算 OK: 空闲 {free_gb:.1f}GB / 建议 {required_gb:.1f}GB')
    except Exception:
        pass


def _estimate_trace_timeout_seconds(n_pairs: int, model_name: str, n_params_m: float = None) -> float:
    """基于模型规模与观测吞吐，估算 TRACE 阶段所需秒数（保守值）。

    经验值（本地 RTX 3050 / 云端 RTX 5090 混合保守估计）:
      - <= 50M params: ~300 pps
      - <= 120M params: ~100 pps
      - 大模型 469M+: ~10 pps（显存与算力瓶颈）

    shehui-llama / shenji-llama 当前均为 ~470M / ~1.8GB 级模型，统一按大模型估算。
    """
    params = n_params_m or 0
    # 若未提供参数量，按模型名做保守兜底（shehui/shenji 都视为 470M）
    name = (model_name or 'shehui-llama').lower()
    if params == 0 and ('shehui' in name or 'shenji' in name):
        params = 470.0

    if params > 200:
        pps = 10
    elif params > 80:
        pps = 50
    elif params > 50:
        pps = 100
    else:
        pps = 300
    return n_pairs / pps


class StageTimer:
    """简易阶段计时器，收集 execution_profile 数据。"""

    def __init__(self):
        self.stages: List[Dict[str, Any]] = []
        self._start = None
        self._name = None

    def begin(self, name: str):
        self._name = name
        self._start = time.time()

    def end(self):
        if self._name and self._start:
            ms = int((time.time() - self._start) * 1000)
            self.stages.append({"stage": self._name, "ms": ms})
            self._name = None
            self._start = None

    def profile(self):
        total = sum(s["ms"] for s in self.stages)
        return {"stages": self.stages, "total_ms": total}


def _check_environment(model_name: str) -> Dict[str, Any]:
    """运行时环境/层级/桥接/算法生存性研判。对应 trace-engine 的 Layer 1+2。"""
    diag = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }

    try:
        paths = resolve_paths()
        model_dir = paths.model_dir(model_name)
        diag["model_dir"] = str(model_dir)
        diag["model_dir_exists"] = model_dir.exists()
        diag["trace_root"] = str(paths.trace_dir)
        diag["skill_dir"] = str(paths.skill_dir)
    except Exception as e:
        diag["model_dir_error"] = str(e)
        diag["model_dir_exists"] = False

    # 显存/CPU 内存粗略估计
    if torch.cuda.is_available():
        try:
            free, total = torch.cuda.mem_get_info(0)
            diag["vram_free_mb"] = int(free / 1e6)
            diag["vram_total_mb"] = int(total / 1e6)
        except Exception:
            pass

    # 模块桥接健康
    modules_status = {}
    for mod in ["counterfactual_bridge", "six_warriors", "dowhy_auditor", "project_paths"]:
        modules_status[mod] = mod in sys.modules
    diag["modules"] = modules_status
    diag["bridge_modules_ok"] = all(modules_status.values())

    return diag


def _compute_token_diagnostics(text: str, sp, model) -> Dict[str, Any]:
    """输入数据质控：token 数、UNK 率、分段数等。"""
    ids = sp.encode(text, out_type=int)
    unk_id = sp.unk_id()
    pad_id = sp.pad_id()
    vocab_size = sp.get_piece_size()
    n_unk = sum(1 for i in ids if i == unk_id)

    max_pos = getattr(model.config, "max_position_embeddings", 256)
    segments = []
    for i in range(0, len(ids), max_pos):
        seg = ids[i:i + max_pos]
        if len(seg) >= 16:
            segments.append(seg)

    return {
        "n_tokens": len(ids),
        "n_segments": len(segments),
        "vocab_size": vocab_size,
        "unk_count": n_unk,
        "unk_ratio": round(n_unk / len(ids), 4) if ids else 0,
        "max_position_embeddings": max_pos,
        "pad_id": pad_id,
        "unk_id": unk_id,
    }


def _algorithm_sufficiency(diagnostics: Dict[str, Any], concepts: List[str], edges: List[Any]) -> Dict[str, Any]:
    """算法/数据充分性研判：给出可操作的诊断信号。"""
    n_tokens = diagnostics.get("n_tokens", 0)
    n_concepts = len(concepts)
    n_edges = len(edges)
    verdicts = []

    if n_tokens < 32:
        verdicts.append("输入 token 数偏少，TRACE 窗口可能不稳定。")
    if n_concepts < 3:
        verdicts.append("概念数不足，DoWhy 识别可能失败或过度简化。")
    if n_edges < 2:
        verdicts.append("显著因果边过少，建议降低 threshold 或增加文本长度。")
    if diagnostics.get("unk_ratio", 0) > 0.15:
        verdicts.append("UNK 率过高，模型词表与输入域不匹配，建议换 Shenji-LLaMA 或改用 DEEP 模式。")

    return {
        "sufficient": len(verdicts) == 0,
        "recommendations": verdicts,
        "n_tokens": n_tokens,
        "n_concepts": n_concepts,
        "n_edges": n_edges,
    }


def _serialize_refutations(refutation_results):
    """将 DoWhy 反驳结果序列化为 JSON 安全字典，兼容 dict/list/None。"""
    if not refutation_results:
        return []

    items = []
    if isinstance(refutation_results, dict):
        for label, r in refutation_results.items():
            items.append((label, r))
    elif isinstance(refutation_results, (list, tuple)):
        for r in refutation_results:
            items.append((getattr(r, 'method', 'unknown'), r))
    else:
        return []

    out = []
    for label, r in items:
        check = getattr(r, '_check', None) or {}
        new_effect = getattr(r, 'new_effect', None)
        try:
            new_effect = float(new_effect) if new_effect is not None else None
        except Exception:
            new_effect = None
        out.append({
            "label": str(label),
            "method": getattr(r, 'method', str(label)),
            "new_effect": new_effect,
            "refuted": bool(check.get('refuted')) if isinstance(check, dict) else bool(getattr(r, 'refuted', False)),
            "display_metric": check.get('display_metric') if isinstance(check, dict) else None,
            "display_label": check.get('display_label') if isinstance(check, dict) else None,
        })
    return out


# ══════════════════════════════════════════════════════════════════════
# 模型加载与缓存
# ══════════════════════════════════════════════════════════════════════
class ModelCache:
    """按模型名称缓存已加载的模型与 tokenizer。"""

    def __init__(self):
        self._models = {}
        self._sps = {}

    def load(self, model_name: str):
        if model_name in self._models:
            return self._models[model_name], self._sps[model_name]

        stage("model_load", f"正在加载 {model_name} 模型...", 0.0)
        paths = resolve_paths()
        model_dir = paths.model_dir(model_name)
        if not model_dir.exists():
            raise FileNotFoundError(f"未找到模型目录: {model_dir}")

        # SentencePiece CJK 路径 workaround
        tmp = tempfile.mkdtemp()
        spm_path = os.path.join(tmp, "spm.model")
        shutil.copy(str(model_dir / "spm.model"), spm_path)
        sp = spm.SentencePieceProcessor()
        sp.load(spm_path)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # 加载前根据模型名估算 VRAM 预算（shehui/shenji 均为 ~470M / ~1.8GB，需要约 3.5GB+）
        name_lower = model_name.lower()
        estimated_params_m = 470.0 if ('shenji' in name_lower or 'shehui' in name_lower) else 100.0
        _check_vram_budget(estimated_params_m, device)

        # 量化加载策略：默认优先 FP16（速度+显存双赢），失败自动回退 FP32
        model_dtype_env = os.environ.get('TRACE_MODEL_DTYPE', 'auto').lower()
        effective_dtype = 'fp32'
        load_kwargs = {}

        if device.type == 'cuda' and model_dtype_env in ('auto', 'fp16', 'float16'):
            try:
                load_kwargs['torch_dtype'] = torch.float16
                model = LlamaForCausalLM.from_pretrained(str(model_dir), **load_kwargs)
                model = model.to(device)
                effective_dtype = 'fp16'
            except Exception as e:
                log('warn', f'FP16 加载失败，回退 FP32: {e}')
                load_kwargs = {}
                model = LlamaForCausalLM.from_pretrained(str(model_dir), **load_kwargs).to(device)
        else:
            model = LlamaForCausalLM.from_pretrained(str(model_dir), **load_kwargs).to(device)

        model.eval()

        n_params = sum(p.numel() for p in model.parameters()) / 1e6
        # 加载后根据实际参数量再次检查（更精确）
        _check_vram_budget(n_params, device)
        log("info", f"模型 {model_name} 已加载: {n_params:.1f}M params, vocab={sp.get_piece_size()}, device={device}, dtype={effective_dtype}")

        self._models[model_name] = model
        self._sps[model_name] = sp
        return model, sp


MODEL_CACHE = ModelCache()
TRACE_CACHE = {}  # text_hash -> (adj_matrix, tokens)


# ══════════════════════════════════════════════════════════════════════
# TRACE 因果发现（基于 LLaMA）
# ══════════════════════════════════════════════════════════════════════
def compute_trace(
    text: str, model, sp, window: int = 64, max_segments: int = 4,
    prune_min_freq: int = 1, max_candidates_per_step: int = 64
):
    """使用 LLaMA 模型计算 token-level ΔNLL 因果矩阵。

    内部会定期发送 stage 进度事件与心跳日志，避免长文本推理时前端长时间无反馈。
    支持 TRACE 剪枝：按历史频率过滤候选、限制每步最大候选数，以在几乎不影响
    因果检出的前提下显著降低大模型推理量。
    """
    device = next(model.parameters()).device
    MASK = sp.piece_to_id('<mask>')
    PAD = sp.pad_id()
    MAX_POS = model.config.max_position_embeddings

    full_ids = sp.encode(text, out_type=int)
    segments = []
    for i in range(0, len(full_ids), MAX_POS):
        seg = full_ids[i:i + MAX_POS]
        if len(seg) >= 16:
            segments.append(seg)

    if len(segments) > max_segments:
        idxs = [0, len(segments) // 3, 2 * len(segments) // 3, len(segments) - 1]
        segments = [segments[i] for i in idxs if i < len(segments)]

    n_segments = len(segments)
    all_raw_edges = defaultdict(list)
    all_tokens = []

    t0 = time.time()
    total_pairs_est = _estimate_trace_pairs(segments, window)
    total_pairs = 0
    processed_pairs = 0
    last_progress = -1.0
    last_progress_time = 0.0
    last_heartbeat = t0
    last_stats_time = t0

    for si, seq in enumerate(segments):
        L = len(seq)
        tokens = [sp.id_to_piece(i) for i in seq]
        offset = len(all_tokens)
        all_tokens.extend(tokens)

        log("info", f"TRACE segment {si+1}/{n_segments}: {L} tokens")

        tn = torch.tensor([seq], dtype=torch.long).to(device)
        with torch.no_grad():
            nl = model(tn).logits

        local_edges = 0
        skipped_candidates_total = 0
        for ti in range(1, L):
            tid = seq[ti]
            hist_start = max(0, ti - window)
            history = seq[hist_start:ti]
            candidates = [t for t in set(history) if t not in (MASK, PAD)]
            if not candidates:
                continue

            # TRACE 剪枝：按历史出现频率排序，过滤低频、截断高频 Top-K
            if prune_min_freq > 1 or len(candidates) > max_candidates_per_step:
                hist_counter = Counter(history)
                candidates = [c for c in candidates if hist_counter[c] >= prune_min_freq]
                candidates = sorted(candidates, key=lambda c: hist_counter[c], reverse=True)
                if len(candidates) > max_candidates_per_step:
                    skipped_candidates_total += (len(candidates) - max_candidates_per_step)
                    candidates = candidates[:max_candidates_per_step]
            if not candidates:
                continue

            prob = torch.clamp(F.softmax(nl[0, ti - 1].float(), dim=-1), 1e-8, 1.0)
            nll_n = -torch.log(prob[tid]).item()

            for bs in range(0, len(candidates), 16):
                batch_c = candidates[bs:bs + 16]
                b_seqs, valid = [], []
                for cid in batch_c:
                    sm = list(seq)
                    masked = False
                    for idx in range(ti):
                        if sm[idx] == cid:
                            sm[idx] = MASK
                            masked = True
                    if masked:
                        b_seqs.append(sm)
                        valid.append(cid)

                if not b_seqs:
                    continue

                bt = torch.tensor(b_seqs, dtype=torch.long).to(device)
                with torch.no_grad():
                    lm = model(bt).logits[:, ti - 1].float()
                pm = torch.clamp(F.softmax(lm, dim=-1), 1e-8, 1.0)[:, tid]
                nll_m = -torch.log(pm).detach().cpu().numpy()

                for ci, cid in enumerate(valid):
                    dnl = max(0.0, nll_m[ci] - nll_n)
                    for pos_idx, tok in enumerate(seq[:ti]):
                        if tok == cid:
                            global_pos = offset + pos_idx
                            target_pos = offset + ti
                            all_raw_edges[(global_pos, target_pos)].append(dnl)
                            local_edges += 1
                            processed_pairs += 1

            # 进度与心跳：每 2% 或 30 秒汇报一次，避免前端/代理因长时间无数据断开连接
            now = time.time()
            if now - last_stats_time >= 3.0:
                stats(processed_pairs, total_pairs_est, now - t0)
                last_stats_time = now
            progress = (si + ti / L) / n_segments if n_segments else 0
            if (progress - last_progress >= 0.02 and now - last_progress_time >= 0.5) or now - last_heartbeat >= 30:
                stage("trace", f"TRACE 计算中... segment {si+1}/{n_segments}, token {ti}/{L}, 已运行 {now - t0:.1f}s", round(progress, 2))
                last_progress = progress
                last_progress_time = now
                last_heartbeat = now

        total_pairs += local_edges
        gc.collect()
        if device.type == 'cuda':
            torch.cuda.empty_cache()

    elapsed = time.time() - t0
    prune_info = f", skipped_candidates={skipped_candidates_total}" if skipped_candidates_total else ""
    log("info", f"TRACE done: {total_pairs} pairs in {elapsed:.1f}s{prune_info}")
    # 最终统计快照
    stats(processed_pairs, total_pairs_est, elapsed)

    T = len(all_tokens)
    adj_matrix = np.zeros((T, T))
    for (i, j), vals in all_raw_edges.items():
        adj_matrix[i, j] = np.mean(vals) if vals else 0.0

    n_nonzero = int((adj_matrix > 0).sum())
    max_dnl = float(adj_matrix.max())
    log("info", f"Adjacency: {T}x{T}, {n_nonzero} non-zero edges, max ΔNLL={max_dnl:.3f}")
    return adj_matrix, all_tokens


# ══════════════════════════════════════════════════════════════════════
# 完整 SUPER 管线
# ══════════════════════════════════════════════════════════════════════
def _merge_llama_presets(model_name: str, config: dict) -> dict:
    """对 Shehui/Shenji-LLaMA V4 模型应用 llama 专项预设作为默认值。"""
    name = (model_name or '').lower()
    if 'shehui' not in name and 'shenji' not in name:
        return dict(config)
    try:
        p = load_presets('llama')
        defaults = {
            'threshold': p.trace2dowhy.threshold,
            'window_size': p.super.window_size,
            'max_segments': p.super.max_segments,
            'concept_min_freq': p.trace2dowhy.concept_min_freq,
            'max_edges_for_dowhy': p.trace2dowhy.max_edges_for_dowhy,
            'filter_mode': p.trace2dowhy.filter_mode,
            'filter_percentile': p.trace2dowhy.filter_percentile,
            'classical_mode': getattr(p.trace2dowhy, 'classical_mode', False),
            'random_state': getattr(p.trace2dowhy, 'random_state', 42),
            'max_concepts': getattr(p.trace2dowhy, 'max_concepts', 12),
            'sem_regularization': getattr(p.counterfactual, 'sem_regularization', None),
            'sem_alpha': getattr(p.counterfactual, 'sem_alpha', 0.01),
            'prune_min_freq': 1,
            'max_candidates_per_step': 64,
        }
        merged = dict(defaults)
        merged.update(config)
        return merged
    except Exception as e:
        log('warn', f'加载 llama 预设失败，使用硬编码默认: {e}')
        return dict(config)


def run_super_job(job: dict):
    """执行一个 SUPER 模式任务并输出事件流。"""
    text = job.get('text', '')
    model_name = job.get('model', 'shehui-llama')
    raw_config = job.get('config', {})
    config = _merge_llama_presets(model_name, raw_config)
    timer = StageTimer()

    if not text or not text.strip():
        error("输入文本为空")
        return

    stage("init", f"SUPER 任务启动 [模型={model_name}]", 0.0)
    timer.begin("init")

    # 0. 环境/层级/桥接生存性研判
    env_diag = _check_environment(model_name)
    log("info", f"环境研判: torch={env_diag['torch_version']}, cuda={env_diag['cuda_available']}, model_dir_exists={env_diag.get('model_dir_exists')}")
    if not env_diag.get('model_dir_exists'):
        error(f"模型目录不存在: {env_diag.get('model_dir')}。请确认 trace-engine 与 trace-engine-web 处于同一层级目录，且模型已同步。")
        return
    timer.end()

    # 1. 加载模型
    timer.begin("model_load")
    try:
        model, sp = MODEL_CACHE.load(model_name)
    except Exception as e:
        error(f"模型加载失败: {e}")
        return
    timer.end()

    # 1.2 模型规模感知：大模型（469M+）应用安全上限，同时尊重 llama 专项预设
    n_params_m = sum(p.numel() for p in model.parameters()) / 1e6
    is_huge = n_params_m > 200
    log("info", f"模型规模: {n_params_m:.1f}M params, max_position={model.config.max_position_embeddings}")
    if is_huge:
        # FP16 量化后显存压力显著降低，允许 llama 预设的 window=128/max_segments=3
        safe_window = 128
        safe_segments = 3
        if config.get('window_size', 64) > safe_window:
            config = dict(config)
            config['window_size'] = safe_window
            log("warn", f"检测到超大模型（{n_params_m:.0f}M），window_size 已限制为 {safe_window}。")
        if config.get('max_segments', 4) > safe_segments:
            config = dict(config)
            config['max_segments'] = safe_segments
            log("warn", f"超大模型下 max_segments 已限制为 {safe_segments}，以减少重复推理。")

    # 1.5 输入数据质控 + 长度预检
    timer.begin("input_diagnostics")
    token_diagnostics = _compute_token_diagnostics(text, sp, model)
    log("info", f"输入质控: tokens={token_diagnostics['n_tokens']}, segments={token_diagnostics['n_segments']}, unk={token_diagnostics['unk_ratio']:.2%}")

    min_tokens = max(16, config.get('min_valid_tokens', 10))
    if token_diagnostics['n_tokens'] < min_tokens:
        error(f"输入文本过短，无法执行 token-level TRACE。当前 {token_diagnostics['n_tokens']} tokens，至少需要 {min_tokens} tokens。")
        return

    # 1.6 耗时预检：在真正计算前告诉用户大致需要多久，避免长时间黑盒等待
    window = config.get('window_size', 64)
    max_segments = config.get('max_segments', 4)
    MAX_POS = model.config.max_position_embeddings
    full_ids = sp.encode(text, out_type=int)
    segments = []
    for i in range(0, len(full_ids), MAX_POS):
        seg = full_ids[i:i + MAX_POS]
        if len(seg) >= 16:
            segments.append(seg)
    if len(segments) > max_segments:
        idxs = [0, len(segments) // 3, 2 * len(segments) // 3, len(segments) - 1]
        segments = [segments[i] for i in idxs if i < len(segments)]
    est_pairs = _estimate_trace_pairs(segments, window)
    est_seconds = _estimate_trace_timeout_seconds(est_pairs, model_name, n_params_m)
    # SUPER 模式不再以固定时间作为硬限制；timeout_ms 仅作为参考上限用于前端提示
    # shehui / shenji 当前均为 ~470M 大模型，统一使用 30 分钟参考上限
    name_lower = model_name.lower()
    is_large_llama = 'shehui' in name_lower or 'shenji' in name_lower
    default_timeout = 3600000 if is_huge else (1800000 if is_large_llama else 300000)
    timeout_ms = job.get('timeout_ms') or default_timeout
    log("info", f"耗时预估: {len(full_ids)} tokens -> 约 {est_pairs} 对因果计算，TRACE 阶段预计 {est_seconds:.0f}s (参考上限 {timeout_ms // 1000}s；可在前端主动停止)")
    if est_seconds * 1000 > timeout_ms * 0.7:
        log("warn", f"预估耗时接近 {timeout_ms // 60000} 分钟参考上限。作为研报级分析可继续等待；如无法接受，可随时在前端点击停止。亦可缩短文本、减小 window_size / max_segments，或切换到 DEEP 模式。")
    timer.end()

    # 2. TRACE 因果发现（带缓存）
    text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    cache_key = f"{model_name}:{text_hash}"
    timer.begin("trace")

    if cache_key in TRACE_CACHE:
        adj_matrix, tokens = TRACE_CACHE[cache_key]
        log("info", "命中 TRACE 结果缓存")
    else:
        stage("trace", "使用 LLaMA 执行 token-level TRACE 因果发现...", 0.2)
        try:
            adj_matrix, tokens = compute_trace(
                text, model, sp,
                window=config.get('window_size', 64),
                max_segments=config.get('max_segments', 4),
                prune_min_freq=config.get('prune_min_freq', 1),
                max_candidates_per_step=config.get('max_candidates_per_step', 64)
            )
            if len(tokens) == 0:
                error("TRACE 未产生有效 token 对，可能是文本过短或模型无法编码输入。")
                return
            TRACE_CACHE[cache_key] = (adj_matrix, tokens)
        except Exception as e:
            error(f"TRACE 计算失败: {e}")
            return
    timer.end()

    # 3. DoWhy 桥接
    timer.begin("bridge")
    stage("bridge", "TRACE → DoWhy 桥接...", 0.5)
    try:
        bridge = TRACE2DoWhy(
            adj_matrix=adj_matrix,
            token_list=tokens,
            threshold=config.get('threshold', 0.03),
            concept_min_freq=config.get('concept_min_freq', 2),
            max_edges_for_dowhy=config.get('max_edges_for_dowhy', 12),
            filter_mode=config.get('filter_mode', 'topn'),
            filter_percentile=config.get('filter_percentile', 85),
            random_state=config.get('random_state', 42),
            classical_mode=config.get('classical_mode', False),
            max_concepts=config.get('max_concepts', 12),
            sem_regularization=config.get('sem_regularization'),
            sem_alpha=config.get('sem_alpha', 0.01),
        )
        bridge.aggregate_concepts()
        bridge.build_model()
        bridge.identify()
        bridge.estimate()
        bridge.refute()
        bridge.counterfactual_scan(n_top_edges=min(5, len(bridge.significant_edges)))
    except Exception as e:
        error(f"DoWhy 桥接失败: {e}")
        return
    timer.end()

    # 4. 算法充分性研判
    sufficiency = _algorithm_sufficiency(token_diagnostics, bridge.concept_names, bridge.significant_edges)
    if not sufficiency["sufficient"]:
        for rec in sufficiency["recommendations"]:
            log("warn", f"算法充分性: {rec}")

    # 5. 六战士诊断
    timer.begin("six_warriors")
    stage("six_warriors", "六战士合体诊断...", 0.8)
    try:
        cards = assemble_all_six(adj_matrix, tokens, bridge=bridge, text=text[:500])
    except Exception as e:
        log("warn", f"六战士诊断部分失败: {e}")
        cards = {}
    timer.end()

    # 6. 审计
    timer.begin("audit")
    stage("audit", "DoWhy 审计防火墙...", 0.9)
    try:
        auditor = DoWhyAuditor(bridge)
        audit = auditor.audit('full')
    except Exception as e:
        log("warn", f"审计失败: {e}")
        audit = None
    timer.end()

    # 7. 组装结果
    timer.begin("finalize")
    stage("finalize", "生成 SUPER 报告...", 0.95)
    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est) if est else [None, None]
    identifiable = DoWhy14Adapter.is_identifiable(bridge.identified_estimand) if bridge.identified_estimand else False
    concept_frequencies = dict(Counter(bridge.concept_map.values())) if bridge.concept_map else {}

    result = {
        "success": True,
        "analysis_mode": "super",
        "model": model_name,
        "text_hash": text_hash,
        "concepts": bridge.concept_names,
        "concept_frequencies": concept_frequencies,
        "n_significant_edges": len(bridge.significant_edges),
        "top_edges": [
            {"source": e[0], "target": e[1], "strength": e[2], "direction": "→"}
            for e in bridge.significant_edges[:20]
        ],
        "treatment": bridge.treatment,
        "outcome": bridge.outcome,
        "ate": est.value if est else None,
        "confidence_interval": ci,
        "identifiable": identifiable,
        "refutations": _serialize_refutations(bridge.refutation_results),
        "counterfactual_scan": bridge.scan_results,
        "six_warriors": {k: v.to_dict() if hasattr(v, 'to_dict') else v for k, v in (cards or {}).items()},
        "auditor": {
            "verdict": audit.verdict if audit else None,
            "n_pass": audit.n_pass if audit else 0,
            "n_warn": audit.n_warn if audit else 0,
            "n_fail": audit.n_fail if audit else 0,
        } if audit else None,
        "execution_profile": timer.profile(),
        "data_diagnostics": token_diagnostics,
        "environment_diagnostics": env_diag,
        "algorithm_sufficiency": sufficiency,
        "threshold": bridge.threshold,
        "window_size": config.get('window_size', 64),
        "max_concepts": config.get('max_concepts', 12),
        "concept_min_freq": config.get('concept_min_freq', 2),
        "backend": "DoWhy",
        "simulation": False,
    }
    timer.end()

    emit({"type": "result", "payload": result})
    stage("done", "SUPER 分析完成", 1.0)


# ══════════════════════════════════════════════════════════════════════
# Worker 主循环
# ══════════════════════════════════════════════════════════════════════
def main():
    log("info", "LLaMA Worker 已启动，等待任务...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except json.JSONDecodeError as e:
            error(f"无法解析任务 JSON: {e}")
            continue
        try:
            run_super_job(job)
        except Exception as e:
            error(f"任务执行异常: {e}")


if __name__ == "__main__":
    main()
