# Counterfactual-DoWhy Hybrid Strategy for TRACE Engine

> **定位**: 将反事实推理（Counterfactual Reasoning）与 DoWhy 因果推断框架
> 整合到 TRACE 四合一线中，形成 **第五维度** 的因果验证能力。

---

## 1. 背景：珍珠的因果阶梯与 TRACE 的定位

Judea Pearl 将因果推理分为三个层级（Ladder of Causation）：

```
层级 3: 反事实 (Counterfactual)  ←  "如果当时 X 不同，Y 会怎样？"
        |                            需要完整的 SCM + 外展-行动-预测三步
        |
层级 2: 干预 (Intervention)      ←  "如果我做 X，Y 会变吗？"
        |                            do(X=x), 后门调整, 工具变量
        |
层级 1: 关联 (Association)       ←  "X 和 Y 相关吗？"
                                     P(Y|X), 相关性, 回归
```

**TRACE 当前所处的位置**：

| 组件 | 因果层级 | 方法 |
|------|---------|------|
| TRACE ΔNLL | 层级 2（虚拟干预） | `do(x_i = [MASK])` 通过掩码模拟 |
| CCM | 层级 1-2（非线性关联→因果） | 交叉映射收敛判定 |
| EDM | 层级 1（可预测性/结构骨架） | 单纯形投影预测 |
| HAVOK | 层级 1-2（强迫项检测） | Koopman 线性+非线性分解 |

**TRACE 尚未到达层级 3**：它不能回答"如果这个词的含义不同，论证结构会如何变化？"

这正是 DoWhy + 反事实推理填补的空白。

---

## 2. DoWhy 是什么？

**DoWhy**（Microsoft Research, 2018-）是一个因果推断库，实现了 Pearl 的
do-calculus 框架。它的核心流程是四个步骤：

```
Model → Identify → Estimate → Refute
  │        │          │          │
  │        │          │          └── 4. 反驳测试（安慰剂、随机共因、数据子集）
  │        │          └── 3. 估计因果效应（后门、IV、倾向得分…）
  │        └── 2. 识别：这个效应能从观测数据中估计吗？
  └── 1. 建模：画因果图 (DAG) + 指定 SCM
```

### DoWhy 提供的 TRACE 当前缺乏的能力：

| 能力 | DoWhy | TRACE 现状 |
|------|-------|-----------|
| 因果图形式化 | ✅ 显式 DAG + SCM | ⚠️ 邻接矩阵，无 SCM |
| 可识别性检查 | ✅ do-calculus 判定 | ❌ 无 |
| 多方法估计 | ✅ 后门/IV/倾向得分/… | ❌ 仅 ΔNLL |
| 反驳测试 | ✅ 随机共因/安慰剂/数据子集 | ❌ 仅 CCM（跨方法） |
| 反事实查询 | ✅ 外展→行动→预测 | ❌ 无 |

---

## 3. 混合策略：TRACE → DoWhy 桥接架构

### 3.1 五层防御体系（原三层 + 新增两层）

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: Environment Validation                            │  ← check_env.py
│  "能跑吗？"                                                  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2: Configuration Audit (Firewall)                    │  ← trace_plus.py
│  "参数组合物理上可行吗？"                                     │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3: CCM Cross-Validation                              │  ← ccm_causality.py
│  "两套独立因果方法同意吗？"                                   │
├─────────────────────────────────────────────────────────────┤
│  LAYER 4: DoWhy Identification + Refutation  ★NEW          │  ← counterfactual_bridge.py
│  "因果效应在形式上可识别吗？反驳测试通过吗？"                  │
├─────────────────────────────────────────────────────────────┤
│  LAYER 5: Counterfactual Query Engine  ★NEW                │  ← counterfactual_bridge.py
│  "如果改变 X，Y 的预测会如何变化？"                            │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
[输入文本]
    │
    ▼
[TRACE] ──→ 因果邻接矩阵 A[i,j] = ΔNLL(x_i → x_j)
    │
    ├──► [Token → Concept 聚合]
    │      高频 token 合并为语义概念节点
    │
    ├──► [DoWhy 建模]
    │      G = nx.DiGraph(A)
    │      model = dowhy.CausalModel(data, graph=G, ...)
    │
    ├──► [识别]  ← Layer 4
    │      identified = model.identify_effect()
    │      输出: 可识别/不可识别 + 估计方法
    │
    ├──► [估计]  ← Layer 4
    │      estimate = model.estimate_effect(identified, ...)
    │      输出: 因果效应量 + 置信区间
    │
    ├──► [反驳]  ← Layer 4
    │      refute_random_cause, refute_placebo, refute_subset
    │      输出: 每个反驳测试的 p 值 → 稳健性评分
    │
    └──► [反事实] ← Layer 5
           cf = model.counterfactual(observed, treatment, control)
           输出: "如果 X 取不同值，Y 会是多少？"
```

### 3.3 与原有四合一仪器的关系

| 仪器 | 测量维度 | DoWhy 补充 |
|------|---------|-----------|
| TRACE (探照灯) | 因果边发现 | 形式化 DAG + 可识别性 |
| CCM (测谎仪) | 非线性纠缠验证 | 反驳测试（更强的鲁棒性检验） |
| EDM (节拍器) | 结构骨架/时间刚性 | 时间序列的因果效应量 |
| HAVOK (X光机) | 隐藏驱动力 | 反事实："如果没有这个驱动力？" |

---

## 4. 实现细节

### 4.1 Token → Concept 桥接

TRACE 的输出是 token 级邻接矩阵。DoWhy 需要概念级变量。桥接策略：

```python
def tokens_to_concepts(adj_matrix, token_list, min_freq=2):
    """
    聚合策略:
    1. 相同 token 的出现合并为一个概念节点
    2. token 间 ΔNLL → 概念间平均 ΔNLL
    3. 低频 token（出现 < min_freq）合并为 "other" 节点
    """
```

### 4.2 从邻接矩阵构建 SCM

```python
def adj_to_dowhy_model(adj_matrix, concept_names, data_df):
    """
    1. 筛选显著边（ΔNLL > threshold）
    2. 构建 DOT 格式的因果图
    3. 创建 DoWhy CausalModel
    4. 数据矩阵: rows=文本段落, cols=概念的 tf-idf 或出现次数
    """
```

### 4.3 反事实查询

```python
def counterfactual_query(model, observed_data, treatment_var, 
                         control_value, treatment_value):
    """
    Pearl 的三步反事实推理:
    1. Abduction:  用观测数据更新外生变量 U 的分布
    2. Action:     do(T = treatment_value)
    3. Prediction: 计算 Y 在干预后的值
    
    回答: "给定我们观测到的文本，如果 concept_X 的强调程度不同，
            concept_Y 的出现概率会如何变化？"
    """
```

---

## 5. 混合策略的适用场景

### 场景 A: 论证文 → 全管线激活

```
论述文（有明确的因果声明链）
  → TRACE 发现密集因果边
  → CCM 验证（信任度 40-60%）
  → DoWhy 识别 → 可识别 ✓
  → DoWhy 反驳 → 通过 ✓
  → 反事实查询 → "如果作者对 X 的立场更激进，论证链如何变化？"
  → 输出: 高度可信的因果图 + 反事实推演
```

### 场景 B: 叙事文 → DoWhy 降级

```
叙事文（时间线推进，token 稀疏）
  → TRACE 发现稀疏边
  → CCM 信任度 < 10%（token 频率不足）
  → DoWhy 识别 → 可能不可识别（样本量不足）
  → 降级策略: 段落级聚合 + bootstrap 重采样
  → 反事实查询 → 受限（只能回答段落间关系）
```

### 场景 C: 混合/不确定 → DoWhy 作为仲裁

```
TRACE 边多但 CCM 信任度中等
  → DoWhy 反驳测试作为第三仲裁方
  → 三个方法投票:
    - TRACE: 边存在
    - CCM: 不确定
    - DoWhy refutation: p > 0.05 → 边可能是虚假的
  → 仲裁结果: 降级该边的置信度
```

---

## 6. 五合一诊断矩阵

| 文本类型 | TRACE | CCM | EDM | HAVOK | DoWhy+Counterfactual |
|---------|-------|-----|-----|-------|---------------------|
| 论证文 | ★★★★★ | ★★★★☆ | ★★★★☆ | ★★★★★ | ★★★★★ (全管线) |
| 叙事文 | ★★★☆☆ | ★★☆☆☆ | ★★★★☆ | ★★★★☆ | ★★☆☆☆ (降级模式) |
| 描述文 | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ | ★★★☆☆ (bootstrap) |
| 对话/辩论 | ★★★★☆ | ★★★★☆ | ★★★☆☆ | ★★★★☆ | ★★★★★ (反事实高价值) |

---

## 7. 文件清单

```
counterfactual_hybrid/
├── README.md                       ← 本文件
├── counterfactual_bridge.py        ← TRACE → DoWhy 桥接模块
├── test_case.py                    ← 可运行的测试案例
└── outputs/                        ← 测试输出
    └── (运行时生成)
```

---

## 8. 依赖

```
pip install dowhy>=0.11.1
pip install networkx>=3.0
pip install numpy>=1.24
pip install pandas>=2.0
pip install scipy>=1.10
```

如果 DoWhy 未安装，桥接模块会以 **模拟模式** 运行——使用相同的 API 结构，
但用统计模拟替代 DoWhy 的正式 do-calculus，让用户可以先体验完整管线。

---

## 9. 参考

- Pearl, J. (2009). *Causality: Models, Reasoning, and Inference*. Cambridge.
- Pearl, J. & Mackenzie, D. (2018). *The Book of Why*. Basic Books.
- Sharma, A. & Kiciman, E. (2020). DoWhy: An End-to-End Library for Causal Inference. *arXiv:2011.04216*.
- Blöbaum, P. et al. (2024). DoWhy-GCM: An Extension of DoWhy for Causal Graphical Models. *arXiv:2206.06821*.
- TRACE: Math & Lienhart (2026). *arXiv:2602.01135*.
- CCM: Sugihara et al. (2012). *Science*, 338(6106), 496-500.
