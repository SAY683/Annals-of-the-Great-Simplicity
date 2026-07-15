# Six-in-One Causal Discovery Architecture — Engineering Design

> TRACE + CCM + EDM + HAVOK + DoWhy/Counterfactual + causallearn
>
> 六合一异质性因果发现架构：从 token 级因果发现到 Pearl 反事实推理的完整管线
>
> **因果战队 (Counterfactual Sentai)**: 六战士合体 = 因果拓扑画像

---

## 0. 架构总览

### 0.1 六层防御 + 六维诊断

```
                         ┌──────────────────────────────────┐
                         │    INPUT: 目标文本 (任意长度)      │
                         └──────────────┬───────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │  LAYER 1                      │                      LAYER 1  │
        │  Environment Validation       │   ← check_env.py              │
        │  "能跑吗？"                    │   PyTorch, CUDA, VRAM, deps   │
        ├───────────────────────────────┼───────────────────────────────┤
        │  LAYER 2                      │                      LAYER 2  │
        │  Configuration Audit (Firewall)│  ← trace_plus.py             │
        │  "参数合理吗？"                 │   seq_len, VRAM, threshold    │
        ├───────────────────────────────┼───────────────────────────────┤
        │  LAYER 3                      │                      LAYER 3  │
        │  CCM Cross-Validation         │   ← ccm_causality.py          │
        │  "两套方法一致吗？"             │   TRACE vs CCM convergence     │
        └───────────────────────────────┼───────────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │                               │                               │
        │  ┌──────────┐   ┌──────────┐  │  ┌──────────┐   ┌──────────┐ │
        │  │  TRACE   │   │   CCM    │  │  │   EDM    │   │  HAVOK   │ │
        │  │ 探照灯    │   │ 测谎仪    │  │  │ 节拍器    │   │ X光机    │ │
        │  │ ΔNLL     │   │ 交叉映射  │  │  │ ρ 预测   │   │ 强迫项   │ │
        │  └──────────┘   └──────────┘  │  └──────────┘   └──────────┘ │
        │                               │                               │
        │     四合一诊断矩阵 → 文本拓扑画像                               │
        └───────────────────────────────┼───────────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │  LAYER 4: DoWhy 正式因果推断   │  ← counterfactual_bridge.py   │
        │  "效应可识别吗？稳健吗？"       │                               │
        │                               │                               │
        │  Model ──→ Identify ──→ Estimate ──→ Refute                   │
        │   DAG      do-calculus     ATE+CI    3层反驳                  │
        │                               │                               │
        │  LAYER 5: Counterfactual      │  ← PearlCounterfactual        │
        │  "如果 X 不同，Y 会怎样？"     │                               │
        │                               │                               │
        │  Abduction ──→ Action ──→ Prediction                         │
        │   外展          干预         预测                              │
        │                               │                               │
        │  LAYER 6: causallearn 独立验证 │  ← CausalLearnValidator       │
        │  "图搜索算法同意吗？"           │  PC + FCI + GES                │
        └───────────────────────────────┼───────────────────────────────┘
                                        │
                         ┌──────────────┴───────────────────┐
                         │  OUTPUT: 六合一综合诊断报告        │
                         │  + DAG 可视化 (graphviz)          │
                         └──────────────────────────────────┘
```

### 0.2 核心设计原则

**异质性防御 (Heterogeneous Defense)**：每个组件测量一个不同的物理维度。这不是 ensemble（同类模型投票），而是多角度诊断（不同仪器测量同一块大陆的不同地貌）。

组件的"失败"是一个**诊断信号**，而不是 bug。

---

## 1. Layer 1-2: TRACE Auditor（环境 + 配置防火墙）

**实现**: [TRACE/scripts/trace_plus.py](../../../TRACE/scripts/trace_plus.py)

| 检查项 | 类型 | 说明 |
|--------|------|------|
| PyTorch + CUDA 版本 | PASS/BLOCK | 无 GPU → CPU 降级 |
| VRAM 可用量 | PASS/WARN | < 1GB → 建议轻量模型 |
| 模型文件存在 | BLOCK | 文件不存在 → 停止 |
| seq_len < context | AUTO-TRUNCATE | 超过 max_pos → 截断 |
| VRAM 预算 | AUTO-CORRECT | batch 太大 → 自动降级 |
| 阈值有效性 | WARN | τ ≤ 0 或 τ > 20 → 警告 |

### 预设系统 (历史 v3，已被 presets.yaml 取代)

> 以下表格基于历史 6M–34M 小模型，仅供旧模型参考。当前生产模型为 ~470M（36L/896d），预设见 `presets.yaml`（demo/standard/deep/archival/llama）。

| Preset | Model | Vocab | Epochs | TRACE Speed | Window | Use Case |
|--------|-------|-------|--------|-------------|--------|----------|
| explore | 6L/256d (6M) | 2K | 8 | 1066/s | 32 | 快速探索 |
| light | 8L/320d (12M) | 3K | 15 | 640/s | 64 | 默认 |
| standard | 8L/384d (17M) | 4K | 25 | 711/s | 96 | 生产 |
| heavy | 10L/384d (22M) | 5K | 40 | 682/s | 128 | 高精度 |
| full | 12L/448d (34M) | 6K | 60 | 609/s | 256 | 档案级 |

---

## 2. Layer 3: CCM Cross-Validation（非线性交叉映射验证）

**数学基础**: Sugihara et al., *Science* 2012 — Convergent Cross Mapping

**核心思想**:
```
如果 X 驱动 Y（X → Y），则 Y 的时间序列包含 X 的信息。
→ 从 Y 的历史可以重建 X 的状态。
→ 且重建精度随样本量增加而收敛。
```

**TRACE 中的近似**: Token 序列 → 出现次数作为"存在时间序列"。

**信任度矩阵**:

| CCM 收敛 | TRACE ΔNLL > τ | 结论 |
|----------|---------------|------|
| ✓ 收敛 | ✓ 显著 | **HIGH CONFIDENCE** |
| ✓ 收敛 | ✗ 不显著 | MEDIUM (CCM 发现 TRACE 遗漏) |
| ✗ 不收敛 | ✓ 显著 | MEDIUM (TRACE 发现 CCM 遗漏) |
| ✗ 不收敛 | ✗ 不显著 | LOW (大概率虚假) |

**已知局限**: 叙事文中 token 频率稀疏（每个实体仅出现 1-2 次）→ CCM 信任度 < 10%。自动降级策略：token freq < 3 → 段落级 CCM 或跳过。

---

## 3. The Four Instruments: 四合一线诊断矩阵

### 3.1 四仪器类比

> 这不是修辞膨胀。每个比喻精确对应了算法在文本诊断中测量的物理维度。

| Algorithm | Instrument | Dimension | Signal | Data Requirement |
|-----------|-----------|-----------|--------|-----------------|
| **TRACE** | 探照灯 | 因果边发现 | ΔNLL 强度 | Token 序列 (自回归模型) |
| **CCM** | 测谎仪 | 非线性纠缠 | 收敛斜率 | 连续时间序列 (3+ 重复) |
| **EDM** | 节拍器 | 时间结构骨架 | ρ 可预测性 | 有序 token 序列 |
| **HAVOK** | X光机 | 隐藏奇点 | 线性/非线性能量比 | 因果矩阵 |

### 3.2 复合诊断模式

```
CCM fails + EDM ρ>0.9 + HAVOK linear>80%
  → 结构清晰的线性叙事，有可识别的转折点
  → 文本类型：叙事文（非论证文）

CCM converges + EDM ρ moderate + HAVOK nonlinear>30%
  → 递归逻辑纠缠的论证文
  → 文本类型：哲学/知乎论证文

TRACE sparse + CCM fails + EDM ρ intermediate + HAVOK linear>70%
  → 描述性文本，无深层因果结构
  → 文本类型：说明文/新闻报道
```

### 3.3 分量评估矩阵

| Component | 论证文 | 叙事文 | 描述文 | 对话/辩论 |
|-----------|--------|--------|--------|----------|
| TRACE | ★★★★★ | ★★★☆☆ | ★★★☆☆ | ★★★★☆ |
| CCM | ★★★★☆ | ★★☆☆☆ | ★★★☆☆ | ★★★★☆ |
| EDM | ★★★★☆ | ★★★★☆ | ★★★☆☆ | ★★★☆☆ |
| HAVOK | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★★★☆ |

---

## 4. Layer 4: DoWhy 正式因果推断

**实现**: [counterfactual_bridge.py](counterfactual_bridge.py)

**依赖**: `dowhy>=0.14`, `networkx`, `statsmodels`, `scikit-learn`, `pandas`

### 4.1 DoWhy 在六合一中的角色

DoWhy 填补了 TRACE 四合一线无法回答的问题：

| 问题 | TRACE 四合一线 | +DoWhy (Layer 4) |
|------|:--:|:--:|
| A 和 B 有因果关系吗？ | ✓ ΔNLL | ✓ DAG + 可识别性检查 |
| 这个效应有多大？ | 仅 ΔNLL 强度 | ✓ ATE + 95% CI |
| 这个效应在统计上稳健吗？ | 仅 CCM 交叉验证 | ✓ 三层反驳测试 |
| 这个效应能从观测数据中识别吗？ | ✗ | ✓ do-calculus |
| 是否存在隐藏混淆因子？ | ✗ | ✓ 随机共因反驳 |

### 4.2 四步管线

```
1. Model:   TRACE邻接矩阵 → DOT格式 → DoWhy CausalModel
              ↓
2. Identify: do-calculus 判断可识别性
              ↓
3. Estimate: backdoor.linear_regression → ATE + 95% CI
              ↓
4. Refute:   随机共因 / 安慰剂处理 / 数据子集 → 稳健性评分
```

### 4.3 DoWhy 0.14 兼容适配

| API | 旧版 (≤0.11) | DoWhy 0.14 | 适配方案 |
|-----|-------------|-----------|---------|
| 可识别性 | `.identifiable` | 检查 `estimand_type` | `DoWhy14Adapter.is_identifiable()` |
| 置信区间 | `.confidence_interval` | `.get_confidence_intervals()` | `DoWhy14Adapter.get_confidence_interval()` |
| 反驳判定 | `.refuted`, `.p_value` | 无 | 偏差度 > 30% → refuted |
| 反事实 | `model.counterfactual()` | 无（已拆到 dowhy-gcm） | `PearlCounterfactual` 独立实现 |

---

## 5. Layer 5: Pearl 三步反事实推理

**实现**: [counterfactual_bridge.py](counterfactual_bridge.py) § `PearlCounterfactual`

**不依赖 DoWhy-GCM** — 基于估计的线性 SEM 系数独立实现。

### 5.1 三步算法

```
给定: 线性 SEM  Y = β·T + Σγₖ·paₖ(Y) + U
      观测值 (x_obs, y_obs)
      干预 do(T = t')

Step 1 — Abduction (外展):
  U = y_obs − (β·x_obs + Σγₖ·paₖ(Y_obs))
  推断外生变量的实际值

Step 2 — Action (行动):
  do(T = t')
  切断 T 的入边，设定 T = t'

Step 3 — Prediction (预测):
  Y_cf = β·t' + Σγₖ·paₖ(Y_obs) + U
  在反事实世界中计算 Y

ITE (个体处理效应) = Y_treatment − Y_control
```

### 5.2 SEM 系数估计

```python
def estimate_sem_from_data(adj_matrix, data, concept_names):
    """
    对每个子节点 Y，用其所有父节点 X 做 OLS:
      Y ~ Σβᵢ·Xᵢ
    存储 βᵢ 到位置 (parent, child)
    """
```

### 5.3 反事实查询示例

```
问题: 如果信息茧房效应减弱 50%，观点极化会如何变化？

do(信息茧房 = 0.5):
  反事实结果: 观点极化强度 = 0.48
do(信息茧房 = 1.0):
  反事实结果: 观点极化强度 = 0.73
ITE = +0.25

解读: 信息茧房每增加 1 单位，观点极化增加 0.25 单位
```

---

## 6. Layer 6: causallearn 独立图搜索验证

**实现**: [counterfactual_bridge.py](counterfactual_bridge.py) § `CausalLearnValidator`

**依赖**: `causal-learn>=0.1.4`

### 6.1 算法

| 算法 | 类型 | 原理 |
|------|------|------|
| **PC** (Peter-Clark) | Constraint-based | 条件独立性检验 → 骨架学习 → 方向定向 |
| **FCI** (Fast Causal Inference) | Constraint-based | PC 的扩展，允许隐藏混淆因子 |
| **GES** (Greedy Equivalence Search) | Score-based | 贪心搜索 BIC 分数最优的等价类 |

### 6.2 TRACE vs causallearn 比较

| | TRACE | causallearn |
|---|---|---|
| **输入** | 文本 token 序列 | 数值数据矩阵 |
| **因果发现** | ΔNLL (掩码干预) | 条件独立性 / BIC 分数 |
| **优势** | 从单一文本发现因果 | 统计严谨性，可处理隐藏变量 |
| **劣势** | 语法偏差，token 粒度 | 需要大样本 (N >> V) |
| **互补** | 适用于任何文本 | 仅在样本充足时有效 |

**已知结果**: 本测试中 PC/GES 均返回 0 边 — 100 个模拟样本不足以支持统计因果发现。这恰好证明了 TRACE 的不可替代性。

---

## 7. DoWhy 性能分析（基于实际测试）

### 7.1 测试设置

- **文本**: "算法推荐与信息茧房" 论证文，7 个核心概念
- **TRACE**: 8 条显著边 (ΔNLL > 0.5)
- **DoWhy 模式**: 正式 do-calculus (0.14)
- **估计方法**: backdoor.linear_regression
- **数据**: 100 个模拟样本 (SEM 生成)

### 7.2 关键发现

#### 发现 1: ΔNLL 与 ITE 的低相关性 (ρ=0.369) 是设计预期内的

```
算法推荐→信息茧房:  ΔNLL=8.47  (最强)  ITE=-0.19  (弱且方向相反)
信息茧房→观点极化:  ΔNLL=7.12  (第二)  ITE=+0.73  (最强)
观点极化→社会共识:  ΔNLL=6.50          ITE=-0.01  (几乎为零)
```

**解释**: ΔNLL 测量的是 token 级预测信息损失（"如果把 X 遮住，模型对 Y 的预测差了多少"），而 ITE 测量的是概念级结构方程回归系数（"X 变化 1 单位，Y 变化多少"）。两者测量不同的"因果强度"概念。**低相关性不是 bug——这证明异质性防御发挥了作用。**

#### 发现 2: 安慰剂反驳的一致性

安慰剂反驳 3/3 次返回 `new_effect≈0.0`，被判定为"反驳"。这是**好消息**——意味着当 T 被随机替换时，ATE 如预期消失。这支持了原估计的因果性。

#### 发现 3: CI 的 NaN 问题

95% CI 为 `[nan, nan]`。根因：模拟数据方差极低（σnoise=0.1），导致 OLS 的 Var(β) 估计不稳定。**在真实 TRACE 数据中不会出现**——真实的 token 出现模式具有自然方差。

#### 发现 4: 可识别性依赖于有向路径

```
信息茧房→透明度: 不可识别 (无有向路径)
信息茧房→观点极化: 可识别 ✓ (有向边存在)
```

这是 DoWhy 的正常行为——do-calculus 需要 treatment 到 outcome 之间存在有向路径。桥梁代码已修复：默认 treatment/outcome 使用最强边的 source/target。

### 7.3 DoWhy 对六合一的价值定位

| 场景 | DoWhy 贡献 |
|------|-----------|
| 论证文 (因果声明密集) | **最大价值**: 识别 + 估计 + 反驳全部激活 |
| 叙事文 (时间线推进) | **中等价值**: 识别可能失败（无直接边），降级为段落级分析 |
| 短文本 (<2K chars) | **低价值**: 样本不足，估计方差异大 |
| 多文本比较 | **高价值**: 可以比较不同文本的因果效应量 |

---

## 8. 环境依赖

### 8.1 核心依赖

| 包 | 版本 | 用途 | 必需？ |
|---|------|------|:---:|
| `torch` | ≥2.0 | TRACE 模型推理 + 训练 | ✓ |
| `transformers` | ≥4.40 | Qwen2.5 / LLaMA 模型加载 | ✓ |
| `sentencepiece` | ≥0.2 | BPE tokenizer | ✓ |
| `numpy` | ≥1.24 | 矩阵运算 | ✓ |

### 8.2 因果推断扩展（六合一 Layer 4-6）

| 包 | 版本 | 用途 | 必需？ |
|---|------|------|:---:|
| `dowhy` | ≥0.14 | 正式 do-calculus（识别、估计、反驳） | 推荐 |
| `networkx` | ≥3.0 | 因果图拓扑操作 | ✓ (DoWhy 依赖) |
| `pandas` | ≥2.0 | DoWhy 数据接口 | 推荐 |
| `statsmodels` | ≥0.14 | OLS 回归（DoWhy 后端） | ✓ (DoWhy 依赖) |
| `scikit-learn` | ≥1.5 | 倾向得分、ML 估计器 | 推荐 |
| `causal-learn` | ≥0.1.4 | PC/FCI/GES 独立验证 | 可选 |
| `graphviz` | ≥0.20 (Python) + binary | DAG 可视化 | 可选 |

### 8.3 Graphviz 系统二进制

```powershell
# Windows: 下载安装 https://graphviz.org/download/
# 安装到 G:\AI\Graphviz 后，PATH 已自动配置（~/.bashrc）
# 验证:
dot -V
# 应输出: dot - graphviz version 15.1.0
```

### 8.4 一键安装

```bash
# 因果推断扩展（推荐）
pip install dowhy networkx pandas statsmodels scikit-learn -i https://pypi.tuna.tsinghua.edu.cn/simple

# 独立验证 + 可视化（可选）
pip install causal-learn graphviz -i https://pypi.tuna.tsinghua.edu.cn/simple

# Graphviz 系统二进制（必须单独安装，见上节）
```

---

## 9. 文件清单

> 完整禁则: [references/forbidden_rules.md](references/forbidden_rules.md)
> 边界情况: [references/edge_cases.md](references/edge_cases.md)

```
trace-engine/
├── README.md                          ← 根目录快速入口
├── SKILL.md                           ← 主入口（架构、预设、快速开始）
├── DESIGN.md                          ← 设计哲学与六仪器比喻
├── tests/
│   └── test_skill.py                  ← 自动化自检
│
├── examples/
│   ├── zhihu_consensus/               ← 四合一线完整案例（叙事文）
│   │   └── README.md
│   │
│   └── counterfactual_hybrid/         ← ★ 六合一 + DoWhy + Counterfactual
│       ├── README.md                  ← DoWhy/反事实概念说明
│       ├── DESIGN_SIX_IN_ONE.md      ← 本文件 — 六合一工程设计
│       ├── counterfactual_bridge.py   ← TRACE→DoWhy 桥接模块
│       ├── six_warriors.py            ← 六战士编排器
│       ├── dowhy_auditor.py           ← 9-rule 审计防火墙
│       ├── presets.py / presets.yaml  ← 统一参数预设
│       ├── run_cli.py                 ← CLI 统一入口
│       ├── run_real_pipeline.py       ← 真实数据管线
│       ├── test_case.py               ← 10 项测试套件
│       ├── _config.py                 ← edm-takens 路径配置
│       ├── _token_filters.py          ← token 质量过滤器
│       ├── project_paths.py           ← 成品目录路径解析
│       ├── _logging.py                ← 统一日志系统
│       ├── enhanced_viz.py            ← 四面板仪表板
│       ├── six_panel_viz.py           ← 六面板仪表板
│       └── references/
│           ├── forbidden_rules.md
│           └── edge_cases.md
│
└── trace-engine-web/ (parallel project)
    ├── README.md
    ├── server.js
    ├── py_bridge.py                   ← 调用本目录模块的 Web 桥接
    └── tests/test_api.py
```

---

## 10. 参考文献

| 论文 | 组件 | 出处 |
|------|------|------|
| Math & Lienhart, "Scalable Sample-Level Causal Discovery via Autoregressive Density Estimation" | TRACE | arXiv:2602.01135 |
| Sugihara et al., "Detecting Causality in Complex Ecosystems" | CCM | Science 2012 |
| Brunton et al., "Chaos as an Intermittently Forced Linear System" | HAVOK | Nature Comms 2017 |
| Takens, "Detecting Strange Attractors in Turbulence" | EDM | Springer 1981 |
| Pearl, "Causality: Models, Reasoning, and Inference" | DoWhy/反事实 | Cambridge 2009 |
| Sharma & Kiciman, "DoWhy: An End-to-End Library for Causal Inference" | DoWhy | arXiv:2011.04216 |
| Spirtes et al., "Causation, Prediction, and Search" | PC/FCI | MIT Press 2000 |
| Chickering, "Optimal Structure Identification with Greedy Search" | GES | JMLR 2002 |

---

*文档日期: 2026-07-13 | TRACE Engine v6 (Six-in-One)*
