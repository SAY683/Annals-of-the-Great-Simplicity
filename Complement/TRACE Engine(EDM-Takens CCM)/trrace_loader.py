"""
TRACE Engine — 统一便携加载器 v2

自动检测 LLaMA 架构, 加载模型, 运行 TRACE 因果发现.

用法:
  python trrace_loader.py                          # 列出可用模型 + 演示
  from trrace_loader import load_model, trace       # 代码调用

依存: torch>=2.0, transformers>=4.40, sentencepiece>=0.2, numpy
"""
import os, sys, time, tempfile, shutil, json
from pathlib import Path
from collections import defaultdict

import torch, torch.nn.functional as F, numpy as np
import sentencepiece as spm

_MODEL_ROOT = Path(__file__).parent.resolve()
_AVAILABLE = sorted(
    d.name for d in _MODEL_ROOT.iterdir()
    if d.is_dir() and (d / "model.safetensors").exists()
)


def list_models() -> list:
    return _AVAILABLE


def load_model(name: str):
    """加载指定模型. 自动检测 LLaMA 架构. 返回 (model, sp, info_dict)."""
    model_dir = _MODEL_ROOT / name
    if not model_dir.exists():
        raise FileNotFoundError(f"Model '{name}' not found. Available: {_AVAILABLE}")

    cfg = json.load(open(str(model_dir / "config.json"), encoding="utf-8"))

    # LLaMA: rms_norm_eps or rope_theta present in config
    if "rms_norm_eps" in cfg or "rope_theta" in cfg:
        from transformers import LlamaForCausalLM
        model = LlamaForCausalLM.from_pretrained(str(model_dir))
        arch = "LLaMA"
    else:
        from transformers import GPT2LMHeadModel
        model = GPT2LMHeadModel.from_pretrained(str(model_dir))
        arch = "GPT-2"

    # SentencePiece (ASCII temp dir workaround for C++ backend)
    _tmp = tempfile.mkdtemp()
    shutil.copy(str(model_dir / "spm.model"), os.path.join(_tmp, "spm.model"))
    sp = spm.SentencePieceProcessor()
    sp.load(os.path.join(_tmp, "spm.model"))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device).eval()

    params = sum(p.numel() for p in model.parameters())
    vram = torch.cuda.memory_allocated() / 1e9 if device.type == "cuda" else 0

    info = {
        "name": name, "architecture": arch,
        "params": params, "params_m": round(params / 1e6, 1),
        "vocab": sp.get_piece_size(), "device": str(device),
        "vram_gb": round(vram, 2),
        "mask_id": sp.piece_to_id("<mask>"), "pad_id": sp.pad_id(),
        "max_pos": model.config.max_position_embeddings,
    }
    return model, sp, info


@torch.no_grad()
def trace(model, sp, text: str, threshold: float = 0.5,
          window: int = 64, max_batch: int = 16, verbose: bool = False) -> dict:
    """TRACE 因果发现. 返回 {edges, tokens, elapsed, length, pairs}."""
    MASK = sp.piece_to_id("<mask>"); PAD = sp.pad_id()
    MAX_POS = model.config.max_position_embeddings

    seq = sp.encode(text, out_type=int)
    if len(seq) > MAX_POS:
        if verbose: print(f"[trace] truncating {len(seq)} -> {MAX_POS}")
        seq = seq[:MAX_POS]

    tokens = [sp.id_to_piece(i) for i in seq]; L = len(seq)
    device = model.device

    tn = torch.tensor([seq], dtype=torch.long).to(device)
    nl = model(tn).logits
    raw = np.zeros((L, L)); pp = 0; t0 = time.time()

    for ti in range(1, L):
        tid = seq[ti]; hist = seq[max(0, ti - window):ti]
        cands = [t for t in set(hist) if t not in (MASK, PAD)]
        if not cands: continue
        prob = torch.clamp(F.softmax(nl[0, ti-1].float(), dim=-1), 1e-8, 1.0)
        nll_n = -torch.log(prob[tid]).item()
        for bs in range(0, len(cands), max_batch):
            bc = cands[bs: bs + max_batch]; bseqs = []
            for cid in bc:
                sm = list(seq)
                for idx in range(ti):
                    if sm[idx] == cid: sm[idx] = MASK
                bseqs.append(sm)
            bt = torch.tensor(bseqs, dtype=torch.long).to(device)
            lm = model(bt).logits[:, ti-1].float()
            pm = torch.clamp(F.softmax(lm, dim=-1), 1e-8, 1.0)[:, tid]
            nll_m = -torch.log(pm).detach().cpu().numpy()
            for ci, cid in enumerate(bc):
                s = max(0.0, nll_m[ci] - nll_n)
                for ci2 in [idx for idx, tok2 in enumerate(seq[:ti]) if tok2 == cid]:
                    raw[ci2, ti] = s
            pp += len(bc)

    elapsed = time.time() - t0
    edges = {(i, j): raw[i, j] for i in range(L) for j in range(L)
             if i < j and raw[i, j] > threshold}
    return {"edges": edges, "tokens": tokens, "elapsed": elapsed, "length": L, "pairs": pp}


def report(result: dict, top_k: int = 15) -> str:
    """格式化 TRACE 结果为可读报告."""
    tokens, edges = result["tokens"], result["edges"]
    punct = set(",.，。、；：？！\"\"''「」【】（）《》;:!?\"'()[]{}　▁ ")
    lines = [
        f"TRACE Report | {result['length']} tokens | {len(edges)} edges | "
        f"{result['elapsed']:.1f}s | {result['pairs']/max(0.01,result['elapsed']):.0f} pairs/s",
        f""
    ]
    lines.append(f"Top-{top_k} causal pairs:")
    for rank, ((i, j), s) in enumerate(sorted(edges.items(), key=lambda x: x[1], reverse=True)[:top_k], 1):
        c = tokens[i].replace("▁", ""); e = tokens[j].replace("▁", "")
        if c not in punct and e not in punct and c != e and c and e:
            lines.append(f"  {rank:2d}. [{c}] -> [{e}]  ({s:.3f})")

    concepts = defaultdict(float)
    for (i, j), s in edges.items():
        c = tokens[i].replace("▁", "")
        if c not in punct and c: concepts[c] += s
    lines.append(f"\nTop-10 concepts:")
    for rank, (c, s) in enumerate(sorted(concepts.items(), key=lambda x: x[1], reverse=True)[:10], 1):
        lines.append(f"  {rank:2d}. {c:<20s} Sigma={s:.1f}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"TRACE Engine — Available: {_AVAILABLE}")
    if _AVAILABLE:
        name = _AVAILABLE[0]
        print(f"\nLoading: {name}")
        model, sp, info = load_model(name)
        for k, v in info.items(): print(f"  {k}: {v}")
        r = trace(model, sp, "社会的本质是联系，行为源自思想")
        print(f"\n{report(r)}")
