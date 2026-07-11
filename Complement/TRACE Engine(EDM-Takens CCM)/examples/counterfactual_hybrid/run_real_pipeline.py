"""
Real-Data Six-in-One Pipeline
===============================
使用已训练的 Shehui-LLaMA 模型，在真实 TRACE Skill 案例文本上
运行完整的六合一管线（TRACE → DoWhy → Counterfactual → Auditor → Viz）。

输入: TRACE Skill 案例文本 (自动检测)
模型: Shehui-LLaMA (15.7M, 8L/320d, vocab=4000, loss=0.01)

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
from _paths import resolve_paths

paths = resolve_paths()
MODEL_DIR = paths.model_dir("shehui-llama")
BRIDGE_DIR = paths.bridge_dir
OUTPUT_DIR = paths.outputs_dir / "real"
CACHE_DIR = paths.cache_dir
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 自动查找文本文件
TEXT_FILE = None
for candidate in [
    paths.data_dir() / "测试(什么是？？的真相).txt",
    paths.project_root / "TRACE" / "date" / "测试(什么是？？的真相).txt",
]:
    if candidate.exists():
        TEXT_FILE = candidate
        break

if TEXT_FILE is None:
    # 使用第一个找到的 .txt
    data_dir = paths.data_dir()
    if data_dir.exists():
        txts = list(data_dir.rglob("*.txt"))
        if txts:
            TEXT_FILE = txts[0]

if TEXT_FILE is None:
    raise FileNotFoundError("未找到训练文本文件。请将文本放入 TRACE/date/")

sys.path.insert(0, str(BRIDGE_DIR))
from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter, _DOWHY_AVAILABLE
from dowhy_auditor import DoWhyAuditor
from enhanced_viz import render_dashboard


def log(msg):
    print(f"  {msg}", flush=True)


def main():
    print("=" * 60)
    print("  Real-Data Six-in-One Pipeline")
    print(f"  Model: Shehui-LLaMA  |  Text: {TEXT_FILE.name}")
    print("=" * 60)

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
    model = LlamaForCausalLM.from_pretrained(str(MODEL_DIR)).to(device).eval()
    log(f"Model: {sum(p.numel() for p in model.parameters())/1e6:.1f}M params, "
        f"vocab={sp.get_piece_size()}, device={device}")

    text = open(str(TEXT_FILE), 'r', encoding='utf-8').read().strip()
    log(f"Text: {len(text):,} chars")

    # ═══════════════════════════════════════════════════════════════
    # Step 1: TRACE — compute real ΔNLL adjacency matrix
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 1] TRACE causal discovery...")

    MASK = sp.piece_to_id('<mask>')
    PAD = sp.pad_id()
    MAX_POS = model.config.max_position_embeddings  # 256

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
            hist_start = max(0, ti - 64)  # window=64
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
    for (i, j), vals in all_raw_edges.items():
        adj_matrix[i, j] = np.mean(vals) if vals else 0.0

    n_nonzero = int((adj_matrix > 0).sum())
    max_dnl = float(adj_matrix.max())
    log(f"  Adjacency: {T}x{T}, {n_nonzero} non-zero edges, max ΔNLL={max_dnl:.3f}")

    # ═══════════════════════════════════════════════════════════════
    # Step 2: DoWhy Bridge
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 2] TRACE → DoWhy Bridge...")

    bridge = TRACE2DoWhy(
        adj_matrix=adj_matrix,
        token_list=all_tokens,
        threshold=0.2,  # Real TRACE data has lower ΔNLL than simulated
        concept_min_freq=2,
        random_state=42,
    )
    bridge.aggregate_concepts()
    log(f"  Concepts: {[n for n in bridge.concept_names if n != '<other>' and len(n)>1][:15]}")

    bridge.build_model()
    log(f"  Edges: {len(bridge.significant_edges)} (ΔNLL > {bridge.threshold})")
    if bridge.significant_edges:
        log(f"  Top edge: {bridge.significant_edges[0][0]} → "
            f"{bridge.significant_edges[0][1]} ({bridge.significant_edges[0][2]:.3f})")

    bridge.identify()
    bridge.estimate()
    bridge.refute()
    bridge.counterfactual_scan(n_top_edges=min(5, len(bridge.significant_edges)))

    # ═══════════════════════════════════════════════════════════════
    # Step 3: Auditor
    # ═══════════════════════════════════════════════════════════════
    print("\n[Step 3] DoWhy Auditor...")
    auditor = DoWhyAuditor(bridge)
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
