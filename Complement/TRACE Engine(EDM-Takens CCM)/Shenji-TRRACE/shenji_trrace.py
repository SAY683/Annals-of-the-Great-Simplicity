"""
Shenji-TRRACE — 可移植因果发现引擎

依存: torch, transformers, sentencepiece, numpy
用法:
  from shenji_trrace import ShenjiTRRACE
  engine = ShenjiTRRACE()             # 自动加载同目录下模型
  result = engine.trace("文本...")     # 运行 TRACE
"""
import os, sys, time, tempfile, shutil
from pathlib import Path
from collections import defaultdict

import torch
import torch.nn.functional as F
import numpy as np
import sentencepiece as spm
from transformers import GPT2LMHeadModel

_MODEL_DIR = Path(__file__).parent.resolve()


class ShenjiTRRACE:
    """
    神纪史诗 TRACE 因果发现引擎

    独立运行 — 不需要 Qwen, 不需要联网, 不需要 TRACE 项目文件夹.

    模型规格:
      - 架构: GPT-2 8L/320d/8h (11.2M params)
      - 词表: SentencePiece BPE 4000
      - 训练数据: 神纪史诗
      - 大小: ~44 MB
      - VRAM: ~1.2 GB (GPU fp32)
    """

    def __init__(self, model_dir: str = None):
        """
        Args:
            model_dir: 模型文件夹路径, 默认为本文件所在目录
        """
        self.model_dir = Path(model_dir) if model_dir else _MODEL_DIR

        # SentencePiece 中文路径 workaround
        self._tmp = tempfile.mkdtemp()
        _spm_model = os.path.join(self._tmp, "spm.model")
        shutil.copy(str(self.model_dir / "spm.model"), _spm_model)

        self.sp = spm.SentencePieceProcessor()
        self.sp.load(_spm_model)
        self.PAD = self.sp.pad_id()
        self.MASK = self.sp.piece_to_id("<mask>")
        self.V = self.sp.get_piece_size()

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = GPT2LMHeadModel.from_pretrained(
            str(self.model_dir)
        ).to(self.device).eval()

        self._params = sum(p.numel() for p in self.model.parameters())
        self._vram = (torch.cuda.memory_allocated() / 1e9
                      if self.device.type == "cuda" else 0)

    def __repr__(self):
        return (f"ShenjiTRRACE({self._params/1e6:.1f}M params, "
                f"vocab={self.V}, device={self.device}, vram={self._vram:.1f}GB)")

    def tokenize(self, text: str) -> list:
        """编码文本为 token IDs."""
        return self.sp.encode(text, out_type=int)

    def detokenize(self, ids: list) -> list:
        """解码 token IDs 为字符串列表."""
        return [self.sp.id_to_piece(i) for i in ids]

    @torch.no_grad()
    def trace(self, text: str, threshold: float = 0.5,
              window: int = 64, max_batch: int = 16,
              verbose: bool = True) -> dict:
        """
        对一段文本运行 TRACE 因果发现.

        Args:
            text:      输入文本
            threshold: 因果强度阈值 (保留 >= threshold 的边)
            window:    因果搜索窗口 (只检查前 window 个 token)
            max_batch: GPU 批处理大小
            verbose:   打印进度

        Returns:
            {"edges": {(cause_pos, effect_pos): strength, ...},
             "tokens": [...], "elapsed": ..., "length": ...}
        """
        seq = self.sp.encode(text, out_type=int)
        tokens = [self.sp.id_to_piece(i) for i in seq]
        L = len(seq)

        if verbose:
            print(f"[TRACE] {L} tokens, window={window}, batch={max_batch}")

        tn = torch.tensor([seq], dtype=torch.long).to(self.device)
        nl = self.model(tn).logits

        raw = np.zeros((L, L))
        pp = 0
        t0 = time.time()

        for ti in range(1, L):
            tid = seq[ti]
            hist = seq[max(0, ti - window):ti]
            cands = [t for t in set(hist) if t not in (self.MASK, self.PAD)]
            if not cands:
                continue

            prob = torch.clamp(F.softmax(nl[0, ti-1].float(), dim=-1), 1e-8, 1.0)
            nll_n = -torch.log(prob[tid]).item()

            for bs in range(0, len(cands), max_batch):
                bc = cands[bs: bs + max_batch]
                bseqs = []
                for cid in bc:
                    sm = list(seq)
                    for idx in range(ti):
                        if sm[idx] == cid:
                            sm[idx] = self.MASK
                    bseqs.append(sm)
                bt = torch.tensor(bseqs, dtype=torch.long).to(self.device)
                lm = self.model(bt).logits[:, ti-1].float()
                pm = torch.clamp(F.softmax(lm, dim=-1), 1e-8, 1.0)[:, tid]
                nll_m = -torch.log(pm).detach().cpu().numpy()

                for ci, cid in enumerate(bc):
                    s = max(0.0, nll_m[ci] - nll_n)
                    for ci2 in [idx for idx, tok2 in enumerate(seq[:ti])
                                if tok2 == cid]:
                        raw[ci2, ti] = s
                pp += len(bc)

        elapsed = time.time() - t0
        edges = {(i, j): raw[i, j] for i in range(L) for j in range(L)
                 if i < j and raw[i, j] > threshold}

        if verbose:
            print(f"[TRACE] {pp} pairs in {elapsed:.1f}s ({pp/elapsed:.0f}/s), "
                  f"{len(edges)} edges > {threshold}")

        return {"edges": edges, "tokens": tokens, "elapsed": elapsed, "length": L}

    def report(self, result: dict, top_k: int = 15) -> str:
        """将 TRACE 结果格式化为可读报告."""
        tokens = result["tokens"]
        edges = result["edges"]
        punct = set(",.，。、；：？！""''「」【】（）《》;:!?\"'()[]{}　▁ ")

        lines = [
            f"Shenji-TRRACE Causal Report",
            f"{'='*50}",
            f"Tokens: {result['length']}  |  Edges: {len(edges)}  |  "
            f"Time: {result['elapsed']:.1f}s",
            f"",
            f"Top-{top_k} causal pairs:",
        ]
        for rank, ((i, j), s) in enumerate(
            sorted(edges.items(), key=lambda x: x[1], reverse=True)[:top_k], 1
        ):
            c = tokens[i].replace("▁", "")
            e = tokens[j].replace("▁", "")
            if c not in punct and e not in punct and c != e:
                lines.append(f"  {rank:2d}. [{c}] -> [{e}]  ({s:.2f})")

        # 概念聚合
        concepts = defaultdict(float)
        for (i, j), s in edges.items():
            c = tokens[i].replace("▁", "")
            if c not in punct and len(c) > 0:
                concepts[c] += s

        lines.append(f"\nTop-10 causal concepts:")
        for rank, (c, s) in enumerate(
            sorted(concepts.items(), key=lambda x: x[1], reverse=True)[:10], 1
        ):
            lines.append(f"  {rank:2d}. {c:<16s} Σ={s:.1f}")

        return "\n".join(lines)

    def __del__(self):
        try:
            shutil.rmtree(self._tmp, ignore_errors=True)
        except Exception:
            pass


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Shenji-TRRACE 因果发现")
    parser.add_argument("text", nargs="*", help="待分析文本 (或用 --file)")
    parser.add_argument("--file", type=str, help="从文件读取")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--window", type=int, default=64)
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args()

    if args.file:
        text = open(args.file, "r", encoding="utf-8").read().strip()
    elif args.text:
        text = " ".join(args.text)
    else:
        text = "姬神蜕出皮，其皮钻入我灵，我灵向姬神阐言，汝即彼，彼即汝"

    engine = ShenjiTRRACE()
    print(engine)
    result = engine.trace(text, threshold=args.threshold,
                          window=args.window, max_batch=args.batch)
    print(engine.report(result))
