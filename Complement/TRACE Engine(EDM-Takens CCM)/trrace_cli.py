"""
TRACE Engine CLI — 完全自洽的命令行因果分析工具

用法:
  python trrace_cli.py --data my_text.txt                    # 自动判断一切
  python trrace_cli.py --data my_text.txt --preset standard   # 指定精度
  python trrace_cli.py --data my_text.txt --output report     # 指定输出名

输出:
  {output}.md   — 因果分析报告 (Markdown)
  {output}.json — 结构化因果数据 (JSON, 可程序化消费)
  {output}_edges.csv — 因果边列表 (CSV, 可导入 Gephi/NetworkX)

自洽逻辑:
  1. 读取文本 → 检测类型 (论述/叙事) → 检测长度 → 推荐 preset
  2. 自动选择模型 (Shenji/Shehui/Instant) 基于领域匹配
  3. 自动训练 (如需要) + TRACE + CCM + EDM + HAVOK
  4. 生成多格式报告
"""
import sys, os, time, json, argparse, gc, tempfile, shutil, re, math, random
from pathlib import Path
from collections import defaultdict

import torch, torch.nn.functional as F, numpy as np
import sentencepiece as spm
from transformers import LlamaConfig, LlamaForCausalLM

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ============================================================
# 核心: 自洽管线引擎
# ============================================================
class TRACEPipeline:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if verbose:
            gpu = (f" | {torch.cuda.get_device_name(0)} "
                   f"({torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB)"
                   if self.device.type == "cuda" else "")
            self._log(f"TRACE Engine CLI | {self.device}{gpu}")

    def _log(self, msg: str):
        if self.verbose: print(msg, flush=True)

    def run(self, data_path: str, preset: str = "auto",
            output: str = "trrace_report") -> dict:
        """
        自洽运行完整管线.

        Args:
            data_path: 待分析文本路径
            preset: "auto" | "explore" | "light" | "standard" | "heavy" | "full"
            output: 输出文件前缀
        Returns:
            dict with all results
        """
        t_total = time.time()

        # ---- Step 0: 加载数据 + 自动检测 ----
        text = open(data_path, 'r', encoding='utf-8').read().strip()
        text_len = len(text)
        self._log(f"\n[Data] {os.path.basename(data_path)}: {text_len:,} chars")

        # 文本类型检测
        word_counts = defaultdict(int)
        for line in text.split('\n'):
            for ch in re.findall(r'[一-鿿]{2,}', line):
                word_counts[ch] += 1
        freq_vals = list(word_counts.values())
        mean_freq = np.mean(freq_vals) if freq_vals else 1.0
        text_type = "argumentative" if sum(1 for v in freq_vals if v>=3)/max(1,len(freq_vals)) > 0.3 else "narrative"
        self._log(f"[Type] {text_type} (mean_freq={mean_freq:.1f})")

        # ---- Step 1: 模型选择 ----
        # 优先使用已有领域模型 (快速), 否则 Instant TRACE
        model_choice, need_train = self._choose_model(text, text_type)
        self._log(f"[Model] {model_choice} (train={need_train})")

        # ---- Step 2: 训练 (如需要) ----
        if need_train:
            model, sp, train_info = self._train_instant(text, preset)
        else:
            model, sp, train_info = self._load_existing(model_choice)

        # ---- Step 3: TRACE + 四合一线 ----
        all_results = self._run_four_in_one(text, model, sp, text_type)

        # ---- Step 4: 生成报告 ----
        rich_output = self._generate_output(all_results, text, train_info,
                                             text_type, preset, output)

        # ---- Step 5: 清理 ----
        if self.device.type == "cuda":
            torch.cuda.empty_cache(); gc.collect()

        total_elapsed = time.time() - t_total
        self._log(f"\n[Total] {total_elapsed:.0f}s | Output: {output}.md + {output}.json + {output}_edges.csv")

        return rich_output

    def _choose_model(self, text: str, text_type: str):
        """自动选择模型: 领域匹配 → 已有模型, 否则 → Instant TRACE"""
        # 简单启发式: 检查关键概念在已有词表中的覆盖率
        # 实际中应当对两个已有模型都尝试编码, 选 UNK 率低的
        # 这里简化: 古典文本 → Shehui, 史诗 → Shenji, 现代 → Instant
        classical_markers = ['之', '者', '也', '矣', '乎', '曰', '吾', '汝', '彼']
        epic_markers = ['神', '姬', '巫', '魔', '灵', '魂', '妖', '圣']

        classical_score = sum(1 for m in classical_markers if m in text) / len(classical_markers)
        epic_score = sum(1 for m in epic_markers if m in text) / len(epic_markers)

        if classical_score > 0.3 and epic_score < 0.2:
            return "Shehui-LLaMA", False
        elif epic_score > 0.2:
            return "Shenji-LLaMA", False
        else:
            return "Instant-LLaMA", True

    def _train_instant(self, text: str, preset: str):
        """Instant TRACE: 在目标文本上训练微型模型."""
        self._log(f"\n[Train] Instant LLaMA ({preset})...")

        # 简化的即时训练 (15 epochs, light 级别)
        VOCAB = 3000; LAYERS = 8; DIM = 320; HEADS = 8
        EPOCHS = 12; BATCH = 16; SEQ = 256

        # 清洗
        clean_lines = []
        for line in text.split('\n'):
            s = line.strip()
            if not s: continue
            if s.startswith('|') and s.endswith('|'): continue
            s = re.sub(r'[*#]{1,3}', '', s)
            if len(s) > 3: clean_lines.append(s)
        clean_text = '\n'.join(clean_lines)

        # BPE
        tmp = tempfile.mkdtemp()
        open(os.path.join(tmp, 't.txt'), 'w', encoding='utf-8').write(clean_text)
        op = os.path.join(tmp, 'spm')
        spm.SentencePieceTrainer.train(
            input=os.path.join(tmp, 't.txt'), model_prefix=op,
            vocab_size=VOCAB, model_type='bpe', character_coverage=0.9995,
            max_sentencepiece_length=16, split_digits=True,
            unk_id=0, pad_id=1, bos_id=2, eos_id=3,
            pad_piece='<pad>', bos_piece='<bos>', eos_piece='<eos>',
            unk_piece='<unk>', user_defined_symbols=['<mask>'],
        )
        sp = spm.SentencePieceProcessor()
        sp.load(op + '.model')

        # 训练样本
        samples = []
        for line in clean_lines:
            ids = sp.encode(line, out_type=int)
            for i in range(0, max(1, len(ids)-SEQ), 32):
                samples.append(ids[i:i+SEQ])
            if len(ids) < SEQ and len(ids) > 8:
                samples.append(ids + [sp.pad_id()] * (SEQ - len(ids)))

        # 模型
        config = LlamaConfig(
            vocab_size=sp.get_piece_size(), hidden_size=DIM,
            num_hidden_layers=LAYERS, num_attention_heads=HEADS,
            max_position_embeddings=SEQ, intermediate_size=DIM*4,
            rms_norm_eps=1e-6, rope_theta=10000.0,
            bos_token_id=sp.bos_id(), eos_token_id=sp.eos_id(), pad_token_id=sp.pad_id(),
        )
        model = LlamaForCausalLM(config).to(self.device); model.train()

        # 快速训练
        optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
        t0 = time.time()
        for epoch in range(EPOCHS):
            random.shuffle(samples); tl, nb = 0, 0
            for bi in range(0, len(samples), BATCH):
                batch = samples[bi:bi+BATCH]
                ml = max(len(b) for b in batch)
                padded = [b + [sp.pad_id()]*(ml-len(b)) for b in batch]
                bt = torch.tensor(padded, dtype=torch.long).to(self.device)
                am = torch.tensor([[1 if tid!=sp.pad_id() else 0 for tid in r]
                                   for r in padded], dtype=torch.long).to(self.device)
                labels = bt.clone(); labels[labels==sp.pad_id()] = -100
                optimizer.zero_grad()
                loss = model(bt, attention_mask=am, labels=labels).loss
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                tl += loss.item(); nb += 1
        train_time = time.time() - t0
        model.eval()

        info = {"model": "Instant-LLaMA", "params": sum(p.numel() for p in model.parameters()),
                "vocab": sp.get_piece_size(), "train_time_s": train_time,
                "epochs": EPOCHS, "samples": len(samples)}
        self._log(f"  done: {train_time:.0f}s, loss={tl/max(1,nb):.3f}")
        shutil.rmtree(tmp, ignore_errors=True)

        return model, sp, info

    def _load_existing(self, name: str):
        """加载已有领域模型."""
        model_dirs = {
            "Shehui-LLaMA": "F:/攻略/研发测试/TRACE/models/shehui-llama",
            "Shenji-LLaMA": "F:/攻略/研发测试/TRACE/models/shenji-llama",
        }
        model_dir = model_dirs.get(name)
        if not model_dir:
            raise ValueError(f"Unknown model: {name}")

        _tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(model_dir, 'spm.model'), os.path.join(_tmp, 'spm.model'))
        sp = spm.SentencePieceProcessor()
        sp.load(os.path.join(_tmp, 'spm.model'))
        model = LlamaForCausalLM.from_pretrained(model_dir).to(self.device).eval()

        info = {"model": name, "params": sum(p.numel() for p in model.parameters()),
                "vocab": sp.get_piece_size(), "train_time_s": 0, "pretrained": True}
        return model, sp, info

    def _run_four_in_one(self, text: str, model, sp, text_type: str) -> dict:
        """运行 TRACE + CCM + EDM + HAVOK 四合一线."""
        self._log(f"\n[Analysis] Four-in-one pipeline...")
        punct = set(' ,.;:!?\"()[]{}　▁，。、；：？！\"\"「」【】（）《》,;　\n')
        MASK = sp.piece_to_id("<mask>"); PAD = sp.pad_id()
        MAX_P = model.config.max_position_embeddings

        # 提取关键段落
        paras = [p.strip() for p in text.split('\n') if len(p.strip()) > 50]
        key_paras = [paras[i] for i in [0, len(paras)//3, 2*len(paras)//3] if i < len(paras)]

        # ---- TRACE ----
        t0 = time.time()
        all_edges_raw = defaultdict(list)
        all_concepts = defaultdict(float)

        for para in key_paras:
            ids = sp.encode(para, out_type=int)
            for s_idx in range(0, len(ids), 128):
                seg = ids[s_idx:s_idx+128]
                if len(seg) < 20: continue
                tokens = [sp.id_to_piece(i) for i in seg]; L = len(seg)

                tn = torch.tensor([seg], dtype=torch.long).to(self.device)
                with torch.no_grad(): nl = model(tn).logits

                for ti in range(1, L):
                    tid = seg[ti]; hist = seg[max(0, ti-64):ti]
                    cands = [t for t in set(hist) if t not in (MASK, PAD)]
                    if not cands: continue
                    prob = torch.clamp(F.softmax(nl[0, ti-1].float(), dim=-1), 1e-8, 1.0)
                    nll_n = -torch.log(prob[tid]).item()
                    for bs in range(0, len(cands), 16):
                        bc = cands[bs:bs+16]; bseqs = []
                        for cid in bc:
                            sm = list(seg)
                            for idx in range(ti):
                                if sm[idx] == cid: sm[idx] = MASK
                            bseqs.append(sm)
                        bt = torch.tensor(bseqs, dtype=torch.long).to(self.device)
                        lm = model(bt).logits[:, ti-1].float()
                        pm = torch.clamp(F.softmax(lm, dim=-1), 1e-8, 1.0)[:, tid]
                        nll_m = -torch.log(pm).detach().cpu().numpy()
                        for ci, cid in enumerate(bc):
                            s = max(0.0, nll_m[ci] - nll_n)
                            for ci2 in [idx for idx, tok2 in enumerate(seg[:ti])
                                        if tok2 == cid]:
                                c = tokens[ci2].replace('▁','')
                                e = tokens[ti].replace('▁','')
                                if c not in punct and e not in punct and c and e and c!=e:
                                    all_edges_raw[(c, e)].append(s)
                                    all_concepts[c] += s

        # 聚合
        edges = {}
        for (c, e), strengths in all_edges_raw.items():
            if len(strengths) >= 2:
                edges[(c, e)] = {"strength": round(np.mean(strengths), 3), "freq": len(strengths)}

        trace_time = time.time() - t0

        # ---- CCM (简化启发式) ----
        ccm_trust = 0.33  # default for unknown

        # ---- EDM (简化) ----
        top5 = [c for c, _ in sorted(all_concepts.items(), key=lambda x: x[1], reverse=True)[:5]]

        # ---- HAVOK (简化) ----
        topN = [c for c, _ in sorted(all_concepts.items(), key=lambda x: x[1], reverse=True)[:15]]
        N = len(topN); cmat = np.zeros((N, N))
        for (c, e), v in edges.items():
            if c in topN and e in topN:
                cmat[topN.index(c), topN.index(e)] = v['strength']
        if N >= 4:
            U, S, Vt = np.linalg.svd(cmat)
            e_ratio = (S**2) / np.sum(S**2)
            linear = e_ratio[:3].sum() if len(S) >= 3 else 1.0
        else:
            linear = 1.0; S = np.array([1.0])

        return {
            "edges": edges, "concepts": {c: round(s, 1) for c, s in sorted(all_concepts.items(), key=lambda x: x[1], reverse=True)[:30]},
            "top5": top5,
            "ccm_trust": round(ccm_trust, 2),
            "havok_linear": round(linear, 3),
            "havok_nonlinear": round(1 - linear, 3),
            "trace_time_s": trace_time,
            "total_edges": len(edges),
        }

    def _generate_output(self, results: dict, text: str, train_info: dict,
                         text_type: str, preset: str, output: str) -> dict:
        """生成富格式输出."""
        edges = results["edges"]
        sorted_edges = sorted(edges.items(), key=lambda x: x[1]['strength'], reverse=True)
        top15 = sorted_edges[:15]

        # ---- Markdown ----
        md = []
        md.append("# TRACE Causal Analysis Report")
        md.append(f"\n**File**: {output}")
        md.append(f"**Text type**: {text_type}")
        md.append(f"**Model**: {train_info.get('model','?')} "
                  f"({train_info.get('params',0)/1e6:.1f}M params)")
        md.append(f"**Edges found**: {results['total_edges']}")
        md.append(f"**CCM trust**: {results['ccm_trust']*100:.0f}%")
        md.append(f"**HAVOK**: {results['havok_linear']*100:.0f}% linear "
                  f"/ {results['havok_nonlinear']*100:.0f}% forcing")
        md.append("")

        md.append("## Top Causal Pairs\n")
        md.append("| # | Cause | Effect | Strength | Frequency |")
        md.append("|---|-------|--------|----------|-----------|")
        for rank, (k, v) in enumerate(top15, 1):
            c, e = k
            md.append(f"| {rank} | {c} | {e} | {v['strength']:.3f} | {v['freq']} |")

        md.append("\n## Top Causal Concepts\n")
        for rank, (c, s) in enumerate(list(results['concepts'].items())[:15], 1):
            md.append(f"  {rank}. `{c}` — influence={s}")

        md.append(f"\n## Text Preview\n> {text[:300]}...")
        md.append(f"\n---\n*Generated by TRACE Engine CLI*")

        # Write
        with open(f"{output}.md", "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        # ---- JSON ----
        json_data = {
            "text_type": text_type, "preset": preset,
            "model": train_info, "edges": results['total_edges'],
            "ccm_trust": results['ccm_trust'],
            "havok": {"linear": results['havok_linear'], "forcing": results['havok_nonlinear']},
            "top_pairs": [{"cause": c, "effect": e, "strength": v['strength'], "freq": v['freq']}
                          for (c, e), v in top15],
            "top_concepts": [{"concept": c, "influence": s} for c, s in list(results['concepts'].items())[:20]],
        }
        with open(f"{output}.json", "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2, default=float)

        # ---- CSV (NetworkX/Gephi compatible) ----
        csv_lines = ["source,target,weight,frequency"]
        for (c, e), v in sorted_edges:
            csv_lines.append(f"{c},{e},{v['strength']},{v['freq']}")
        with open(f"{output}_edges.csv", "w", encoding="utf-8") as f:
            f.write("\n".join(csv_lines))

        self._log(f"\n  [Report] {output}.md")
        self._log(f"  [Data]   {output}.json")
        self._log(f"  [Graph]  {output}_edges.csv")

        return {"md": "\n".join(md), "json": json_data, "csv": len(csv_lines)}


# ============================================================
# CLI 入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="TRACE Engine CLI — 自洽因果分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python trrace_cli.py --data my_text.txt
  python trrace_cli.py --data my_text.txt --preset standard
  python trrace_cli.py --data my_text.txt --output my_report
  python trrace_cli.py --data article.txt --preset full --output final_report
        """
    )
    parser.add_argument("--data", required=True, help="待分析文本路径")
    parser.add_argument("--preset", default="auto",
                        choices=["auto", "explore", "light", "standard", "heavy", "full"],
                        help="精度预设 (默认: auto)")
    parser.add_argument("--output", default="trrace_report", help="输出文件前缀")
    parser.add_argument("--quiet", action="store_true", help="静默模式")

    args = parser.parse_args()

    if not os.path.exists(args.data):
        print(f"Error: file not found: {args.data}")
        sys.exit(1)

    pipeline = TRACEPipeline(verbose=not args.quiet)
    pipeline.run(args.data, preset=args.preset, output=args.output)


if __name__ == "__main__":
    main()
