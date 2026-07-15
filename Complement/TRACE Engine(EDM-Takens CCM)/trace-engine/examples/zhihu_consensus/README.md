# Zhihu Consensus Analysis — TRACE+CCM+EDM+HAVOK 四合一线案例

> 案例来源: 知乎网友关于宗族械斗与乡土社会的论述 (5,932 字)
> 分析管线: Instant TRACE → CCM → EDM → HAVOK → 综合诊断
> 运行时间: 训练 83 分钟 + 四合一线 12 秒 (RTX 3050 4GB)

## 运行方法

```bash
python TRACE/scripts/pipeline_zhihu.py
```

## 案例摘要

### 文本特征

- 类型: 叙事文 (宗族械斗故事), 非论述文
- 长度: 5,932 chars, 53 paragraphs
- 主题: 马田村/井冈村宗族冲突, 乡村社会共识的形成与破裂
- 语言: 现代白话 + 方言词汇 (不戴孝, 械斗, 宗族)

### 分析结果

```
TRACE:  22 条显著因果边 (thr>=1.0, UNK=0.1%)
        核心概念: 马田村, 不戴孝, 械斗, 防线, 粮食
        最强因果: [粮食]→[也要] (6.24), [马田村]→[5] (4.55)

CCM:    信任度 3% — 叙事文 token 重复不足
        仅 ["引号配对] 通过交叉映射

EDM:    概念可预测性: ["但是"]=0.99, ["已经"]=0.92
        转折词/完成态高度可预测 → 文本有强叙事结构

HAVOK:  83% 线性 / 17% 非线性强迫
        隐藏驱动力: [此时]=6.9 (时间状语主导叙事)
        线性主导 → 叙事结构清晰, 按时间线推进

判定:   MIXED (混合)
        叙事清晰但因果论证据不足 (单边断言多)
        协调指数: 0% (完全单向叙事, 无论证对话)
```

## 四合一线在叙事文 vs 论述文中的表现

### 论述文 (哲学/知乎论证文)

```
TRACE: 因果边密集 (>50 edges), ΔNLL 信号强
CCM:   信任度 40-60% → 有效交叉验证
EDM:   概念可预测性 0.4-0.7 → 部分概念有动力学结构
HAVOK: 线性 60-70%, 非线性 30-40% → 隐藏驱动力有意义
判定:  通常 COORDINATED 或 MIXED
```

### 叙事文 (故事/回忆录)

```
TRACE: 因果边稀疏 (<30 edges), ΔNLL 信号中等
CCM:   信任度 <10% → token 稀疏导致失效
EDM:   概念可预测性 0.7-0.99 → 叙事结构高度规律
HAVOK: 线性 >80% → 时间线主导
判定:  通常 MIXED (结构清晰但因果论证据弱)
```

### 关键发现: CCM 的适用边界

```
CCM 有效条件:  目标 concept 在文本中至少出现 3+ 次
叙事文满足率:  ~10-20% (每个实体只出现 1-2 次)
论述文满足率:  ~60-80% (关键概念反复讨论)

→ 自动检测: concept freq < 3 → 降级 CCM 为段落级或跳过
→ 已在 DESIGN.md §Known Failure Mode 6 中记录
```

## 算法评估矩阵

| 组件 | 论述文 | 叙事文 | 优化方向 |
|------|--------|--------|---------|
| TRACE | ★★★★★ | ★★★☆☆ | 叙事文降低阈值到 0.5-0.7 |
| CCM | ★★★★☆ | ★★☆☆☆ | 自动检测 token freq, 降级策略 |
| EDM | ★★★★☆ | ★★★★☆ | rho>0.8 → 标记高确定性概念 |
| HAVOK | ★★★★★ | ★★★★☆ | 自适应矩阵大小 |

## 文件清单

```
examples/zhihu_consensus/
├── README.md                    ← 本文件
├── pipeline_zhihu.py            ← (在 TRACE/scripts/ 中)
├── figures/                     ← 运行后生成: 因果图可视化
└── data/
    └── 知乎网友.txt             ← (在 TRACE/date/ 中)
```

## 复现

```python
# 1. Train-on-target（历史小模型，当前生产模型为 shehui-llama 27M / shenji-llama 469M / shehui-llama-v4-archive 470M 归档）
#    -> BPE on 知乎文本, LLaMA 8L/320d, 60 epochs, full augmentation
#    -> UNK=0.1%, loss=0.092

# 2. TRACE
#    -> 554 pairs/s, 22 significant edges

# 3. CCM
#    -> 3% trust → narrative text limitation

# 4. EDM
#    -> Simplex E=2, concept predictability check

# 5. HAVOK
#    -> SVD decomposition, linear vs forcing components

# 6. Synthesis
#    -> 4-score consensus diagnosis
```

## 设计洞察

1. **词表统治一切**: UNK rate 从 30%→0.1%, 因果信号从噪音→干净
2. **文本类型决定 CCM 功效**: 论述文 CCM 有效, 叙事文需要段落级聚合
3. **HAVOK 是通用诊断器**: 不依赖 token 频率, 对所有文本类型都有效
4. **四合一线互补**: TRACE 找边, CCM 验证, EDM 建模式, HAVOK 找隐藏驱动
   任一环节弱不影响其他环节

---

*案例日期: 2026-07-10 | TRACE Engine v1.0*
