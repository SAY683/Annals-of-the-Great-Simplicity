# TRACE Engine — Design Rule Adoption Audit

> 参照: EDM-Takens `secret_adoption_audit.md`
> 更新: 2026-07-10

## 核心设计规则采纳状态

| # | 规则 | 状态 | 实现位置 | 备注 |
|---|------|------|---------|------|
| 1 | 审计防火墙 (3层) | ✅ ADOPTED | trace_plus.py, DESIGN.md | Layer1=env_check, Layer2=audit_trance, Layer3=CCM |
| 2 | Ghost Token 基线 | ✅ ADOPTED | pipeline_zhihu.py §PHASE2 | 减去语法噪音 |
| 3 | 多维动态早停 | ✅ ADOPTED | pipeline_zhihu.py, early_stop.py | 四信号加权判定 |
| 4 | 小词表优先 | ✅ ADOPTED | train_shenji_llama.py | vocab=3000-4000, 非151936 |
| 5 | LLaMA > GPT-2 | ✅ ADOPTED | 所有训练脚本 | RoPE+RMSNorm+SwiGLU |
| 6 | CCM 自动降级 | ✅ ADOPTED | pipeline_zhihu.py §PHASE3 | freq<3 → 段落级 |
| 7 | 自适应阈值 | ✅ ADOPTED | pipeline_zhihu.py | freq-based formula |
| 8 | HAVOK 自适应矩阵 | ✅ ADOPTED | pipeline_zhihu.py §PHASE5 | min(concepts,√N*3) |
| 9 | 段落级训练 | ✅ ADOPTED | 所有训练脚本 | 防止跨段噪音 |
| 10 | 词表与模型分离 | ✅ ADOPTED | 架构设计 | BPE 独立训练, 共享 vocab |

## 部分采纳 / 待完善

| # | 规则 | 状态 | 待修复 |
|---|------|------|--------|
| 11 | 跨模型统一接口 | ⚠️ PARTIAL | trrace_loader 只支持加载, 不含训练 |
| 12 | 自动化测试套件 | ❌ DEFERRED | 无 run_tests.py |
| 13 | GPU 不可用时 CPU 降级 | ⚠️ PARTIAL | 有 device_map="cpu" fallback 但未经充分测试 |
| 14 | 训练/TRACE 参数自动调优 | ❌ DEFERRED | batch/epoch 需手动设 preset |

## 明确拒绝 / 不可行

| # | 规则 | 状态 | 原因 |
|---|------|------|------|
| R1 | Qwen 注意力剪枝 | ❌ REJECTED | Eager+fp16=NaN, SDPA 不支持 output_attentions |
| R2 | GPT-3 架构 | ❌ NOT NEEDED | 与 GPT-2 同骨架, 额外复杂度无收益 |
| R3 | 通用大词表 (151K) | ❌ REJECTED | logits 爆炸, 速度崩溃 100x |
| R4 | 纯目标文本训练 | ❌ INSUFFICIENT | 数据不足 → ΔNLL 弱 → 必须数据增强 |

## 下阶段优先实施

```
P0 (本周): run_tests.py — 自动化验证
P1 (下周): CPU-only 完整测试
P2 (后续): 参数自动调优
```
