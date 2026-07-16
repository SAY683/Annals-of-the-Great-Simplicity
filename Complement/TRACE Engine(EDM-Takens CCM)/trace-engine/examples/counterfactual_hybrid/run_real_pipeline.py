"""
Real-Data Six-in-One Pipeline
===============================
使用已训练的 shehui-llama / shenji-llama / shehui-llama-v4-archive 模型，在真实
TRACE Skill 案例文本上运行完整的六合一管线（TRACE → DoWhy → Counterfactual → Auditor → Viz）。

输入: TRACE Skill 案例文本 (自动检测)
模型:
  - shehui-llama: 27M params, 10L/384d, ~108MB safetensors, max_position=256 (FAST)
  - shenji-llama: 469M params, 36L/896d, ~1.8GB safetensors, max_position=1024
  - shehui-llama-v4-archive: 470M params, 36L/896d, ~1.8GB safetensors, max_position=1024 (旧版归档)

路径解析: 自动检测项目根目录（无需硬编码路径）
"""

import sys, os, time, gc, json, math, re, warnings
from pathlib import Path
from collections import defaultdict

import torch
import torch.nn.functional as F
import numpy as np
import sentencepiece as spm
from transformers import LlamaConfig, LlamaForCausalLM

warnings.filterwarnings('ignore')

# ── 自动路径解析 ──
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_paths import resolve_paths

paths = resolve_paths()
MODEL_DIR = paths.model_dir("shehui-llama")
BRIDGE_DIR = paths.bridge_dir
OUTPUT_DIR = paths.outputs_dir / "real"
CACHE_DIR = paths.cache_dir
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 自动查找文本文件
TEXT_FILE = None
sample_name = "政治意识.txt"
candidate = paths.data_dir() / sample_name
if candidate.exists():
    TEXT_FILE = candidate

if TEXT_FILE is None:
    # 使用第一个找到的 .txt
    data_dir = paths.data_dir()
    if data_dir.exists():
        txts = list(data_dir.rglob("*.txt"))
        if txts:
            TEXT_FILE = txts[0]

if TEXT_FILE is None:
    raise FileNotFoundError(f"未找到训练文本文件。请将文本放入 {paths.data_dir()}/")

sys.path.insert(0, str(BRIDGE_DIR))
from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter, _DOWHY_AVAILABLE
from dowhy_auditor import DoWhyAuditor
from enhanced_viz import render_dashboard
from presets import load_presets
from pipeline_helpers import run_full_pipeline


def log(msg):
    print(f"  {msg}", flush=True)


def _check_vram_budget(n_params_m: float, device: torch.device):
    """模型 VRAM 预算检查：根据参数量估算所需显存，不足时给出警告。

    - 27M 级模型（shehui-llama）: ~1.5GB
    - 470M 级模型（shenji-llama / shehui-llama-v4-archive）: ~3.0GB
    """
    if device.type != "cuda":
        return
    try:
        free_gb = torch.cuda.mem_get_info()[0] / 1e9
        if n_params_m and n_params_m > 200:
            required_gb = 3.0
        elif n_params_m and n_params_m > 50:
            required_gb = 2.0
        else:
            required_gb = 1.5
        if free_gb < required_gb:
            log(f"⚠ VRAM 预算紧张: 空闲 {free_gb:.1f}GB < 建议 {required_gb:.1f}GB")
            log("  建议: 关闭其它 GPU 程序、启用 FP16 量化（llama_worker.py 设置 TRACE_MODEL_DTYPE=fp16），或减少 window_size/max_segments")
        else:
            log(f"VRAM 预算 OK: 空闲 {free_gb:.1f}GB / 建议 {required_gb:.1f}GB")
    except Exception:
        pass


def main():
    print("=" * 60)
    print("  Real-Data Six-in-One Pipeline")
    print(f"  Model: Shehui-LLaMA  |  Text: {TEXT_FILE.name}")
    print("=" * 60)

    # 加载 LLaMA V4 专项预设（ΔNLL 范围与 Qwen 不同，需要更宽松的阈值）
    p = load_presets("llama")
    log(f"Preset: llama | threshold={p.trace2dowhy.threshold} | window_size={p.super.window_size}")

    # ═══════════════════════════════════════════════════════════════
    # Step 0: Load model + data
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 0] Loading model & data...")

    # Cut path copy (SentencePiece CJK path workaround)
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    shutil.copy(str(MODEL_DIR / "spm.model"), os.path.join(tmp, "spm.model"))
    sp = spm.SentencePieceProcessor()
    sp.load(os.path.join(tmp, "spm.model"))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 加载前根据模型目录名估算规模，做 VRAM 预算检查
    # shehui-llama (27M): ~1.5GB | shenji-llama / shehui-llama-v4-archive (470M): ~3.0GB
    model_name_lower = str(MODEL_DIR).lower()
    if "archive" in model_name_lower:
        estimated_params_m = 470.0      # shehui-llama-v4-archive
    elif "shenji" in model_name_lower:
        estimated_params_m = 470.0      # shenji-llama
    elif "shehui" in model_name_lower:
        estimated_params_m = 27.0       # shehui-llama (27M 纯哲学版)
    else:
        estimated_params_m = 100.0      # 未知模型，保守估计
    _check_vram_budget(estimated_params_m, device)

    model = LlamaForCausalLM.from_pretrained(str(MODEL_DIR)).to(device).eval()
    n_params_m = sum(p.numel() for p in model.parameters()) / 1e6
    log(f"Model: {n_params_m:.1f}M params, "
        f"vocab={sp.get_piece_size()}, device={device}")

    # 加载后根据实际参数量再次检查（更精确）
    _check_vram_budget(n_params_m, device)

    with open(str(TEXT_FILE), 'r', encoding='utf-8') as f:
        text = f.read().strip()
    log(f"Text: {len(text):,} chars")

    # ═══════════════════════════════════════════════════════════════
    # Step 1: TRACE — compute real ΔNLL adjacency matrix
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 1] TRACE causal discovery...")

    MASK = sp.piece_to_id('<mask>')
    PAD = sp.pad_id()
    MAX_POS = model.config.max_position_embeddings  # 当前模型为 1024

    # Tokenize into segments
    full_ids = sp.encode(text, out_type=int)
    log(f"Total tokens: {len(full_ids)}")

    # Split into MAX_POS segments
    segments = []
    for i in range(0, len(full_ids), MAX_POS):
        seg = full_ids[i:i + MAX_POS]
        if len(seg) >= 16:
            segments.append(seg)
    log(f"Segments: {len(segments)}")

    # Select representative segments (beginning, middle, end)
    if len(segments) > 3:
        idxs = [0, len(segments)//3, 2*len(segments)//3, len(segments)-1]
        segments = [segments[i] for i in idxs if i < len(segments)]
    log(f"Selected: {len(segments)} segments for TRACE")

    # Run TRACE on each segment
    all_raw_edges = defaultdict(list)
    all_tokens = []
    token_positions = []  # (seg_idx, pos_in_seg) for mapping back

    t0 = time.time()
    total_pairs = 0

    for si, seq in enumerate(segments):
        L = len(seq)
        tokens = [sp.id_to_piece(i) for i in seq]
        offset = len(all_tokens)
        all_tokens.extend(tokens)

        log(f"  Segment {si+1}: {L} tokens")

        # Normal logits
        tn = torch.tensor([seq], dtype=torch.long).to(device)
        with torch.no_grad():
            nl = model(tn).logits

        local_edges = 0
        for ti in range(1, L):
            tid = seq[ti]
            hist_start = max(0, ti - p.super.window_size)  # 使用 llama 预设窗口
            history = seq[hist_start:ti]

            candidates = [t for t in set(history) if t not in (MASK, PAD)]
            if not candidates:
                continue

            # Normal NLL
            prob = torch.clamp(F.softmax(nl[0, ti-1].float(), dim=-1), 1e-8, 1.0)
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
                    lm = model(bt).logits[:, ti-1].float()
                pm = torch.clamp(F.softmax(lm, dim=-1), 1e-8, 1.0)[:, tid]
                nll_m = -torch.log(pm).detach().cpu().numpy()

                for ci, cid in enumerate(valid):
                    dnl = max(0.0, nll_m[ci] - nll_n)
                    for pos_idx in [idx for idx, tok in enumerate(seq[:ti]) if tok == cid]:
                        global_pos = offset + pos_idx
                        target_pos = offset + ti
                        all_raw_edges[(global_pos, target_pos)].append(dnl)
                        local_edges += 1

        total_pairs += local_edges
        gc.collect()
        if device.type == 'cuda':
            torch.cuda.empty_cache()

    elapsed = time.time() - t0
    log(f"  TRACE done: {total_pairs} pairs in {elapsed:.1f}s")

    # Build adjacency matrix
    T = len(all_tokens)
    adj_matrix = np.zeros((T, T))
    # 跨段 dnl 平均：同一 (src, dst) token 对在多段中可能产生多个 ΔNLL 值，
    # 这里取简单均值作为聚合。这是当前设计选择（而非加权/最大值），
    # 因为各段被视为对同一因果结构的独立观测，简单均值是最无偏的估计。
    for (i, j), vals in all_raw_edges.items():
        adj_matrix[i, j] = np.mean(vals) if vals else 0.0

    n_nonzero = int((adj_matrix > 0).sum())
    max_dnl = float(adj_matrix.max())
    log(f"  Adjacency: {T}x{T}, {n_nonzero} non-zero edges, max ΔNLL={max_dnl:.3f}")

    # 保存 TRACE 缓存，供 run_cli.py real 复用并确保六战士诊断使用同一数据
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(str(CACHE_DIR / "real_adj.npy"), adj_matrix)
    (CACHE_DIR / "real_tokens.json").write_text(
        json.dumps(all_tokens, ensure_ascii=False), encoding='utf-8')
    log(f"  TRACE cache saved: {CACHE_DIR}/real_adj.npy, real_tokens.json")

    # ═══════════════════════════════════════════════════════════════
    # Step 2: DoWhy Bridge
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 2] TRACE → DoWhy Bridge...")

    # classical_mode 由 trace2dowhy 预设控制；显式取出后，其余参数用 ** 展开
    trace_kwargs = dict(p.trace2dowhy)
    classical_mode = trace_kwargs.pop('classical_mode', False)
    bridge = TRACE2DoWhy(
        adj_matrix=adj_matrix,
        token_list=all_tokens,
        random_state=42,
        classical_mode=classical_mode,
        **trace_kwargs,
    )
    # debt-05: 管线核心序列抽取到 pipeline_helpers.run_full_pipeline（双轨入口合并）
    run_full_pipeline(bridge, preset=p)

    log(f"  Concepts: {[n for n in bridge.concept_names if n != '<other>' and len(n)>1][:15]}")
    log(f"  Edges: {len(bridge.significant_edges)} (ΔNLL > {bridge.threshold})")
    if bridge.significant_edges:
        log(f"  Top edge: {bridge.significant_edges[0][0]} → "
            f"{bridge.significant_edges[0][1]} ({bridge.significant_edges[0][2]:.3f})")

    # ═══════════════════════════════════════════════════════════════
    # Step 2.5: Six Warriors — 保证 run_real_pipeline 也是完整六合一
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 2.5] Six Warriors diagnostics...")
    try:
        from six_warriors import assemble_all_six
        from six_panel_viz import render_chart_suite
        cards = assemble_all_six(adj_matrix, all_tokens, bridge=bridge, text=text[:500])
        # debt-04 audit 修复：将六战士卡片注入 bridge，激活 report() 中的复合诊断引擎
        bridge.set_six_warriors_cards(cards)
        for key, card in cards.items():
            print(f"  {card.color} {card.warrior_id:12s} [{card.status.upper()}] {card.verdict}")
        charts = render_chart_suite(bridge, cards, str(OUTPUT_DIR), dpi=150)
        log(f"  Six Warriors charts: {len(charts)} files")
    except Exception as e:
        log(f"  Six Warriors: ERROR — {e}")

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Auditor
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 3] DoWhy Auditor...")
    auditor = DoWhyAuditor(bridge, **p.auditor)
    report = auditor.audit('full')
    report.print_report()

    # ═══════════════════════════════════════════════════════════════
    # Step 4: Enhanced Dashboard
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 4] Enhanced Dashboard...")
    try:
        dash_path = render_dashboard(
            bridge,
            str(OUTPUT_DIR / "real_data_dashboard.png"),
            dpi=150,
        )
        log(f"  Dashboard: {dash_path}")
    except Exception as e:
        log(f"  Dashboard: ERROR — {e}")

    # ═══════════════════════════════════════════════════════════════
    # Step 5: Report
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 5] Report...")
    report_text = bridge.report()
    report_path = OUTPUT_DIR / "real_data_report.md"
    report_path.write_text(report_text, encoding='utf-8')
    log(f"  Report: {report_path} ({len(report_text)} chars)")

    # ═══════════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("  Pipeline Complete")
    print("=" * 60)
    print(f"  Mode: {bridge.mode_name}")
    print(f"  Tokens: {T} → Concepts: {len(bridge.concept_names)}")
    print(f"  Edges (real ΔNLL): {len(bridge.significant_edges)}")
    print(f"  Max ΔNLL: {max_dnl:.3f}")
    print(f"  Auditor: {report.verdict} (FAIL={report.n_fail}, WARN={report.n_warn})")
    print(f"  Output: {OUTPUT_DIR}")

    return bridge, report


if __name__ == "__main__":
    bridge, report = main()
