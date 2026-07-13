# TRACE Forbidden Rules — Things You Must Never Do

> 参照: EDM-Takens `references/forbidden_rules_reference.md` (14 条规则)
> TRACE Engine v1.0 定义了 7 条核心禁止规则

## Rule 1: Never TRACE Without Auditing

```
✗ 直接跑 TRACE, 不看 VRAM/seq_len
✓ 先调 auditor → PASS 再跑

原因: 序列过长 → OOM。阈值极端 → 假因果。
      审核器 30ms 跑完, 省几十分钟。
```

## Rule 2: Never Trust ΔNLL Without Ghost Baseline

```
✗ raw ΔNLL 直接当因果强度
✓ 减去 Ghost Token 基线后使用

原因: 语法搭配 (的→了, 因为→所以) 的 ΔNLL 可高达 10+
      但这些不是逻辑因果。Ghost 基线能削掉这部分噪音。
```

## Rule 3: Never Apply Shehui-LLaMA to Modern Vernacular

```
✗ 把 Shehui-LLaMA (古典中文) 用于知乎/微博/现代白话
✓ 检测 UNK rate > 5% → 切换到 Instant TRACE

原因: 古典模型词表不覆盖现代词汇
      → ΔNLL 全变成 <unk>→<unk> 的假信号
```

## Rule 4: Never Skip CCM for Large Causal Graphs

```
✗ TRACE 发现 200+ 条边, 不验证直接引用
✓ 边数 > 100 → 运行 CCM 交叉验证

原因: TRACE 会捕获所有统计依赖, 包括伪因果
      CCM (独立方法) 验证 → 筛选掉大部分噪音
```

## Rule 5: Never Run HAVOK on Small Matrices (< 10×10)

```
✗ 20 个概念做 HAVOK 分解
✓ N ≥ 10 才有意义, N ≥ 20 推荐

原因: SVD 需要足够维度才有意义
      小矩阵 → 全部是噪声 → 无力学可分解
```

## Rule 6: Never Trust Results With < 60% CCM Trust

```
✗ CCM 信任度 7% → "TRACE 说 A→B"
✓ 信任度 < 60% → 标注为 "需要更多证据"
✓   信任度 < 20% → 标注为 "不可信"

原因: CCM < 20% 意味着独立方法完全不同意
      → 大概率是 TRACE 的假阳性
```

## Rule 7: Never Mix Domain Models (Shenji ↔ Shehui)

```
✗ 对哲学文本用 Shenji-LLaMA
✓ 史诗 → Shenji, 古典社会 → Shehui, 现代 → Instant

原因: 每个模型的词表+语境都是专属的
      跨域使用 = 故意引入 UNK 噪声
```
