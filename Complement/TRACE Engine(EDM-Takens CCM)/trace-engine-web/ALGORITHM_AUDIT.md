# TRACE Engine 全量算法检察报告（元思维追踪）

> **方法论：** 不只看"影子"（输出结果），而是追踪"投影过程"（每步数据如何变形、维度如何坍缩、信息如何重组）。每个阶段问三个问题：输入是什么形状、输出是什么形状、什么东西被丢弃了。

---

## 0. 管线的两个运行剖面

| 维度 | LIGHT | DEEP |
|------|-------|------|
| 概念上限 | 12 | 24 |
| 最大边数 | 12 | 20 |
| ATE 估计 | statsmodels OLS 解析解 (~0.1s) | DoWhy bootstrap 100 次 (~1-5min) |
| 反驳测试 | **跳过** | 3 层反驳 (各 ~100 次模拟) |
| 六战士 | **跳过** | TRACE/CCM/EDM/HAVOK/DoWhy/causallearn |
| 稳定性 | **跳过** | bootstrap 边 + 置换检验 + 3 折 CV |
| 预期总耗时 | ~5-10s | ~30s–10min |

---

## Stage 1: read — 输入文本加载

```
输入:  stdin / 文件路径
输出:  text (Python str, 纯 Unicode)
丢弃:  文件元数据（路径、编码、时间戳）
```

**元思维：** 这是唯一"无损失"的阶段——原始文本原样进入内存。但编码探测（UTF-8/GBK/Latin-1）本身隐含了一次不可逆的语义判断：如果一个文件用 Latin-1 读出了乱码，用户不知道"这个字在被读错"。

**潜在地雷：** BOM 头、混合编码、零宽字符——这些都会被静默吸收进 `text` 而不报错，直到分词阶段才暴露。

---

## Stage 2: tokenize — 分词 + 概念过滤

```
输入:  text (str, N 个字符)
       │ jieba.lcut()          ← 基于隐马尔可夫 + Trie 前缀树
       │                       词库: jieba 内置 34.9 万词 + 9 个领域词
       ▼
中间:  tokens (list, T 个 token)
       │ _is_valid_concept_web() ← 单层过滤
       │   ① _token_filters.is_valid_concept(): 标点/空格/纯数字/单字 BPE 碎片  → 丢弃
       │   ② _EXTRA_STOP_CHARS: 100+ 单字停用字 (它/他/她/你/我/的/了...)    → 丢弃
       │   ③ _EXTRA_STOP_WORDS: 80+ 双字停用词 (这种/那种/就是/我们/因此/但是...) → 丢弃
       ▼
输出:  valid_tokens (list, V 个有效概念 token)
丢弃:  T-V 个 token（标点、停用词、虚词、代词、BPE 碎片）
```

**元思维：** 这里发生了第一次"因果意义的坍缩"——jieba 分词本身就假设了"中文词是可切分的连续序列"，这个假设在古典汉语文言文中完全不成立（一个"之"字可能承载主语、宾语、助词三种完全不同的因果角色）。

**潜在地雷：**
- 停用词表是硬编码的（80+ 词），如果用户分析"关于'自我'的哲学文本"，"自我"被静默丢弃
- `classical_mode=false` 时，古汉语虚词（之/乎/者/也）被当作 BPE 碎片扔掉
- 领域词只有 9 个（算法推荐/信息茧房/观点极化…），不同领域的专有名词会被切成碎片

---

## Stage 3: concepts — 高频概念提取

```
输入:  valid_tokens (list, V 个 token)
       │ Counter() → most_common(max_concepts)
       │ max_concepts = 12 (LIGHT) / 24 (DEEP)
       ▼
输出:  concept_names (list, C 个唯一概念名, C ≤ max_concepts)
       concept_frequencies ({name: count})
       ccm_eligible (子集, count ≥ 3)
丢弃:  V 个 token 的时序信息（token 位置序列坍缩为频率计数）
       所有未进入 top-C 的低频 token（信息量可能很高但出现次数不够）
```

**元思维：** 这是管线上第一个"降维 + 丢弃"的决策点。Top-C 截断等价于假设"只有高频概念才承载因果结构"。这个假设在大多数文本中成立，但有一个反例：**一个低频但语义关键的概念（如专有名词"王阳明"只在文中出现 1 次但却是全篇的核心主题）会被丢弃**。

**数据变换：**
```
valid_tokens: ["新","党","建设","推进","社会主义","政治","现代化","时代","习近平","中国共产党","自我","中国",...]
              ↓ 频率排序 + top-12 截断
concept_names: ["新","党","建设","推进","社会主义","政治","现代化","时代","习近平","中国共产党","自我","中国"]
```

---

## Stage 4: graph — 概念因果图构建

```
输入:  tokens (原始 T 个 token)
       concept_names (C 个概念)
       window_size (64)
       │ ① 过滤出在 concept_names 中的 token → token_ids
       │ ② 滑动窗口 (window_size) 内共现计数 → adj[a,b] += 1
       │ ③ 有向剪枝: 若 i→j 共现次数 > j→i 共现次数，则反向边清零
       │ ④ 归一化: adj = adj / adj.max() * 8.0
       ▼
输出:  adj (C×C 矩阵, 对角为 0, 有向)
       n_edges (非零元素计数)
丢弃:  窗口之外的 token 对关系（长程依赖被截断）
       方向不显著的边（对称共现 → 任意归为同一方向）
       原始共现计数（归一化后失去绝对频率信息）
```

**元思维：** 这个阶段是整个管线对"因果性"的**核心近似**——**共现 ≠ 因果**。TRACE 引擎通过窗口共现计数来近似 token 级因果依赖，但这有三个隐含假设：

1. **局部性假设：** 因果影响只在 window_size 距离内有效（64 token ≈ 3-5 句中文字）
2. **方向性假设：** 如果 A 出现在 B 之前且次数比反向多，则 A→B 为因果方向
3. **线性归一化假设：** 除以最大值抹平了所有边的绝对尺度信息

**数据变换（可感知的）：**
```
共现次数 → 有向修剪 → 归一化 ×8.0
原始:  adj[a,b]=23, adj[b,a]=14  →  方向 a→b, adj[a,b]=23, adj[b,a]=0
归一化后: adj[a,b]=23/max×8.0 = (假设 max=23) → 8.0
```

---

## Stage 5: bridge — TRACE2DoWhy 桥接

```
输入:  adj (C×C 概念级矩阵), concept_names (C 个)
       │ TRACE2DoWhy.__init__()
       │   存入 self.adj_matrix (即 adj), self.token_list (即 concept_names)
       │   注意: token_list 此时是概念名列表，不是原始 token 序列
       │
       │ 手动注入 (修复后的关键逻辑):
       │   bridge.concept_adj = adj
       │   bridge.concept_names = concept_names
       │   bridge.concept_idx = concept_idx
       │   这跳过了 aggregate_concepts() —— 因为概念聚合已在 py_bridge 侧完成
       │
       │ build_model():
       │   ① 边过滤: adj > threshold → 提取边 (source, target, strength)
       │   ② 概念有效性过滤: is_valid_concept() 二次检查（实际上已在概念提取时完成）
       │   ③ 边数截断: 若边数 > max_edges_for_dowhy → top-N 或 percentile 或 adaptive
       │   ④ DOT 图生成: 仅包含有效边中出现的节点
       │   ⑤ 数据模拟: _simulate_data(C, n_samples=1000)
       │       使用拓扑排序 + SEM 结构方程生成 1000 行合成观测数据
       │       data[child] += coefficient × data[parent] + noise
       │   ⑥ SEM 系数估计: 从合成数据 + 二值邻接矩阵 → estimate_sem_from_data()
       │   ⑦ 因果模型构建: DoWhy CausalModel 或 SimulationModel
       ▼
输出:  bridge 对象
       ├── significant_edges: [(src, dst, strength), ...]  (≤ max_edges_for_dowhy 条)
       ├── data_df: DataFrame (1000 × C)
       ├── sem_coeff: (C×C) SEM 系数矩阵
       ├── pearl_cf: PearlCounterfactual 引擎
       ├── dot_graph: DOT 格式因果图
       └── model: DoWhy CausalModel 或 SimulationModel
```

**元思维：** 桥接阶段是算法上最关键的一步"翻译"——把 TRACE 的共现矩阵翻译成 DoWhy 能理解的因果图语法。这里的核心决策是：

1. **边过滤的"截断效应"：** threshold 切掉弱边，max_edges_for_dowhy 再切一次。被切掉的边并非"不存在因果"，只是"证据不够强"——这是一个信息论的取舍。

2. **数据模拟的"自指涉"：** DoWhy 需要真正的数据来做回归，但 TRACE 产出的是边权重（非观测数据）。于是 bridge 做了一个巧妙的操作：**用因果图的边权重反过来模拟生成一份看起来像观测数据的 DataFrame**（1000 行 × C 列）。这本质上是一个"生成式模型"——用因果结构生成数据，再用这些数据验证因果结构。

3. **模拟数据的拓扑排序陷阱：** 如果因果图有环（A→B→C→A），拓扑排序会失败，退化为迭代近似（5 次），导致模拟数据未必精确反映原始因果边强度。

---

## Stage 6: identify — 因果效应识别

```
输入:  bridge.model (DoWhy CausalModel), treatment, outcome
       │ model.identify_effect()
       │   do-calculus: 判断 P(outcome | do(treatment=X)) 是否能从观测数据中计算
       │   自动选择识别策略（后门调整 / 前门调整 / 工具变量）
       ▼
输出:  bridge.identified_estimand
       identifiable (bool)
       │ True  → 因果图中无未观测共因，后门路径可阻断
       │ False → 存在未被阻断的后门路径，效应可能被混杂
```

**元思维：** 可识别性是因果推断的"及格线"——不可识别意味着数据中没有足够的信息来唯一确定因果效应。但 **DoWhy 的可识别性检查只对 DOT 图中已有的节点做判断**——如果某个真实存在的混杂变量根本没进入概念列表，DoWhy 也看不到它。

---

## Stage 7: estimate — 因果效应估计

```
LIGHT 路径:
  输入: bridge.data_df, treatment, outcome
        │ _fast_ols_ate_ci()
        │   ① 构造协变量: 除 treatment/outcome 外的所有数值列
        │   ② OLS 回归: y = β₀ + β₁·treatment + Σ βₖ·covariates[k]
        │   ③ HC3 异方差稳健标准误
        │   ④ ATE = β₁, CI = conf_int(treatment)
        ▼
  输出: estimate.value (β₁), CI [lower, upper]
  耗时: ~0.1s

DEEP 路径:
  输入: bridge.model, bridge.identified_estimand
        │ bridge.model.estimate_effect()
        │   method_name="backdoor.linear_regression"
        │   confidence_intervals=True  → 启用 bootstrap
        │   ~100 次 bootstrap 重采样 + 每次重新估计 OLS
        ▼
  输出: estimate.value (ATE), CI [lower, upper]
  耗时: ~1-5min (bootstrap 100次 × OLS on 1000×24 matrix)
```

**元思维：** LIGHT 和 DEEP 在这个阶段存在一个"精度 vs 速度"的根本分歧：

- OLS 解析解（LIGHT）：假设误差项独立同分布（i.i.d.），给出精确的公式解。速度快但可能低估真实不确定性。
- Bootstrap（DEEP）：不假设误差分布，通过反复抽样来近似 ATE 的抽样分布。更稳健但更慢。

**一个被隐藏的信息：** `HC3` 异方差稳健标准误（LIGHT 路径）已经对常见的"方差不齐"做了修正，所以在大多数文本中，LIGHT 的 CI 与 DEEP 的 bootstrap CI 差距不大。DEEP 的额外 3 分钟主要是为论文级别的严谨性买单。

---

## Stage 8: refute — 反驳测试（DEEP 独有）

```
输入:  bridge.model, bridge.identified_estimand, bridge.estimate_result
       │ 反驳器 1 — random_common_cause:
       │   随机添加一个共因变量 → 重新估计 ATE
       │   预期: ATE 不应大幅变化（偏差 < 30%）
       │
       │ 反驳器 2 — placebo_treatment_refuter:
       │   用随机变量替换 treatment → 重新估计 ATE
       │   预期: 随机 treatment 的 ATE 应接近 0（安慰剂效应消失）
       │
       │ 反驳器 3 — data_subset_refuter:
       │   随机抽取 80% 数据子集 → 重新估计 ATE
       │   预期: 子集上的 ATE 应与全量 ATE 相近（偏差 < 30%）
       ▼
输出:  refutations dict
       ├── 随机共因:    {new_effect, deviation, refuted}
       ├── 安慰剂处理:  {new_effect, remaining_ratio, refuted}
       └── 数据子集:    {new_effect, deviation, refuted}
       综合判定: 0/3 反驳 = ROBUST; 2+/3 反驳 = CAUTION
```

**元思维：** 反驳测试是因果推断的"交叉验证"——不是验证"ATE 对不对"，而是验证"ATE 是否可能来自统计巧合"。三个反驳器分别从三个方向攻击：

1. **随机共因：** "你确定没有隐变量？我随便加一个噪声变量试试"
2. **安慰剂：** "你确定 treatment 真的有用？我换一个假的试试"
3. **子集：** "你确定结论普遍成立？我删掉一些数据试试"

如果三个攻击全部失败（0/3 反驳），说明效应极其稳健。

---

## Stage 9: counterfactual — 反事实扫描

```
输入:  bridge.pearl_cf (PearlCounterfactual), top-5 edges
       │ 每条边:
       │   Abduction (溯因): U = Y_obs - (SEM 预测值)
       │       推断"外生噪声"——数据中不能被因果结构解释的部分
       │   Action   (行动): do(T = 1.0)  切断 treatment 的所有入边
       │       在因果模型中执行"干预"，而非"观测"
       │   Prediction(预测): Y_cf = SEM(do(T=1.0)) + U
       │       在干预后的因果图中重新计算 outcome
       │   ITE = Y_cf - Y_obs  (个体因果效应)
       ▼
输出:  scan_results (list of 5)
       ├── source / target: 因果边
       ├── trace_dnl: TRACE 原始边强度
       ├── observed: 在观测数据中 outcome 的实际值
       ├── counterfactual: 在 do(treatment=1.0) 的反事实世界中 outcome 的值
       └── ite: 个体因果效应
```

**元思维：** 反事实是因果推断的皇冠——它不只是在说"A 和 B 相关"，而是在回答 **"如果 A 曾经不同，B 会怎样"** 这个在真实世界中无法观测的问题。

Pearl 三步法的精妙之处在于 **外生噪声 U 的保留**——溯因步骤把观测数据中不能被因果结构解释的部分 U 提取出来，然后反事实预测时把同一个 U 带回去。这保证了反事实世界中的"个体"和真实世界中的是**同一个人**。

**一个微妙的点：** SEM 系数是从模拟数据（Stage 5）估计出来的，所以反事实结果的质量高度依赖于模拟数据是否能准确反映 TRACE 原始因果边强度。如果模拟数据有偏差（例如因为阈值设置不当导致丢失了关键边），反事实 ITE 也会偏。

---

## Stage 10: six_warriors — 六战士诊断（DEEP 独有）

```
输入:  adj (概念级邻接矩阵), tokens (原始 token 序列), bridge
       │ 🔴 TRACE:   统计边数/最大 ΔNLL/UNK 率 → SIGNAL_OK / SIGNAL_WEAK
       │ 🔵 CCM:     频率覆盖率 → NARRATIVE_TEXT (叙事文) / VERIFIABLE / LOW_TRUST
       │ 🟡 EDM:     间隔变异系数 ρ → HEURISTIC_STRONG/LOW_STRUCTURE
       │ ⚫ HAVOK:    SVD 能量分解 → LINEART/MIXED/NONLINEAR
       │ 🟡 DoWhy+CF: ATE + CI + 反驳 → ROBUST / CAUTION
       │ ⬜ causallearn: PC + GES 图搜索 → CONSENSUS / TRACE_ONLY / DIVERGENT
       ▼
输出:  six_warriors dict (6 个 WarriorCard)
```

**元思维：** 六战士的设计哲学是"不是投票，是测绘"。六个完全异构的算法从不同角度测绘同一个文本的"因果拓扑"。关键洞察：

- **某个战士"失败"本身就是诊断信号**——CCM 失败告诉你文本是叙事文而非论证文；HAVOK 非线性占比高告诉你文本存在逻辑突变
- **causallearn 在 N<200 时功效不足是预期行为**——这恰恰证明了 TRACE 在小样本上的不可替代性

---

## Stage 11: stability — 稳定性分析（DEEP 独有）

```
输入:  bridge, tokens, concept_names, adj, estimate
       │ ① Bootstrap 边稳定性 (30 次):
       │    对 token 序列重采样 → 重建概念图 → 检查哪些原始边在新图中出现
       │    高稳定性 → 边不是偶然的（不依赖特定采样）
       │
       │ ② Bootstrap ATE (30 次):
       │    对数据行重采样 → OLS 估计 ATE → 收集 ATE 分布
       │    at_bootstrap_std → ATE 的抽样不确定性
       │
       │ ③ 置换检验 (20 次):
       │    随机打乱 treatment 列 → 重新估计 ATE
       │    若原始 |ATE| 显著大于所有置换后的 |ATE| → p-value 小 → 效应非偶然
       │
       │ ④ K-fold CV (3 折):
       │    3 折交叉验证 → cv_ate_mean, cv_ate_std
       │    低方差 → ATE 估计不依赖于特定数据划分
       ▼
输出:  stability_analysis dict
       ├── edge_stability_mean: 边的 bootstrap 稳定率
       ├── at_bootstrap_std: ATE 的 bootstrap 标准差
       ├── permutation_p_value: 置换检验 p 值
       └── cv_ate_mean/std: 交叉验证 ATE 均值和标准差
```

---

## Stage 12: report — 输出生成

```
输入:  所有上游产出
       │ bridge.report() → Markdown 报告 (7 章)
       │ result dict: 23 个顶层字段 → result.json
       │ SSE: {"type":"result","payload":{...}}
       ▼
输出:  result.json, report.md, SSE result event
```

---

## 全局数据流图

```
text (str)
  │ 丢弃: 编码元数据
  ▼
tokens (T 个 str) → 丢弃: T-V 个停用/虚词/碎片
  │
  ▼
concept_names (C 个 str) → 丢弃: 低频 token（即使有因果价值）
  │
  ▼
adj (C×C float) → 丢弃: 弱边、反向边、绝对频率、长程依赖
  │
  ▼
significant_edges (≤ N 条) → 丢弃: 低于 threshold 或超过 max_edges 的边
  │
  ▼
data_df (1000 × C)  ← 这是从因果图 "反向生成" 的虚拟观测数据
  │
  ▼
ATE + CI + Refutations + CF + Warriors + Stability
  │
  ▼
result.json + report.md
```

## 关键发现与潜在改进

### 值得注意的

1. **共现 ≠ 因果：** 整个管线用一个滑动窗口的"共现度"来近似"因果依赖"。在概念稀疏或句子边界模糊的文本中，这个近似可能失效。SUPER 模式用 LLaMA 的 token-level attention 取代共现，所以更精确。

2. **两次截断的累积效应：** Stage 4 用 threshold 切边 → Stage 5 再用 max_edges_for_dowhy 切边 → 如果 threshold 太低而 max_edges 太小，真正重要的边可能被两轮过滤误杀。

3. **模拟数据的自指涉循环：** data_df 是从因果图生成的，ATE 又是从 data_df 估计的。如果因果图的边结构有系统性偏差，这个偏差会在模拟→估计循环中被放大而非消除。

4. **停用词表不可配置：** 80+ 硬编码停用词和 100+ 单字停用字是静态的。对特定领域（哲学/法律/教育），可能需要不同的停用策略。

### 信号强度在整个管线中的衰减轨迹

```
原始文本: ~200 token（61万 token 量级下）
token 化后: ~200 token
过滤后: ~132 valid tokens
概念化后: 12 个概念
边构建后: ~70 条候选边
过滤后: 8 条显著边
最终: 1 条 treatment→outcome + 5 条反事实扫描边
```

信息维度从 200 个 token 坍缩为 12 个概念，再坍缩为 8 条因果边。每一步都是信息的选择性丢弃——被丢弃的大多数是噪声，但也可能包含有价值的弱信号。
