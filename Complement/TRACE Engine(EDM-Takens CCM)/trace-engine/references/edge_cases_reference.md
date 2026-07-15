# TRACE Edge Cases — Boundary Conditions & Failure Limits

> 本文档记录 TRACE 因果发现在极端和边界条件下的行为。
> 参照: EDM-Takens `references/edge_cases_reference.md`

## 1. 序列长度极端

| 长度 | 行为 | 判定 |
|------|------|------|
| L < 5 | BLOCK (audit) | 无法做因果发现 — token 太少, 没有统计意义 |
| 5 ≤ L < 10 | WARN | 勉强可用, 但 ΔNLL 方差极大, 不宜信任单条边 |
| 10 ≤ L < 256 | PASS | 正常工作范围 |
| 256 < L < 1000 | PASS (分段) | 自动切分为 128-256 token 段 |
| L > 1000 | WARN | 分段 + 跨段聚合, 注意段边界因果丢失 |

## 2. 词表不匹配

| UNK Rate | 行为 | 后果 |
|----------|------|------|
| < 1% | PASS | 词表完美覆盖 (Instant TRACE) |
| 1-5% | WARN | 少量 UNK, ΔNLL 轻度退化 |
| 5-20% | WARN (建议 Instant) | 大部分因果信号被 UNK 噪声淹没 |
| > 20% | FAIL (audit 拦截) | ΔNLL = 噪声, 不建议继续 |

## 3. 文本类型边界

| 类型 | TRACE 功效 | CCM 功效 | 建议 |
|------|-----------|---------|------|
| 论述文 (argumentative) | 强 | 强 (token 重复充分) | 标准参数即可 |
| 叙事文 (narrative) | 中 | 弱 (token 稀疏) | 降阈值, 段落级 CCM |
| 抒情/诗歌 | 弱 | 极弱 | 不建议单独用 TRACE |
| 技术文档/代码 | 不适用 | 不适用 | token 分布不适配 |

## 4. 多语言混合

| 情况 | 行为 |
|------|------|
| 纯中文 | PASS |
| 中英混合 (< 30% 英文) | 可用, 英文 token 会被 BPE 错误切分 |
| 中英混合 (> 30% 英文) | WARN — 考虑用多语言 tokenizer |
| 纯英文/其他语言 | FAIL — 需要对应语言的模型 |

## 5. VRAM 边界（当前模型：shehui-llama / shenji-llama，~470M / 36L/896d / ~1.8GB）

| VRAM 可用 | 建议模式 | 说明 |
|-----------|---------|------|
| < 3 GB | CPU 或 FP16 | FP32 加载权重即占 ~1.9GB，激活/碎片易导致 OOM |
| 3-4 GB | FP16 | 可跑，但需关闭其它 GPU 程序；建议减小 window_size / max_segments |
| > 4 GB | FP32 / FP16 | 安全运行；SUPER 模式大文本仍建议 FP16 |

## 6. 训练数据量边界

> 以下表格基于历史 8M–50M 小模型，仅供旧模型参考。当前生产模型为 ~470M，训练细节见模型训练日志。

| 训练数据 (清洗后) | 模型上限 | Epoch 建议 |
|------------------|---------|-----------|
| < 2K chars | 不推荐训练 | 用已有模型 |
| 2-5K chars | 8L/256d (8M) | 60+ (Instant TRACE) |
| 5-30K chars | 8L/320d (15M) | 15-50 |
| 30-100K chars | 12L/384d (35M) | 15-40 |
| > 100K chars | 12L/448d (50M) | 10-30 |
