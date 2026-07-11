# TRACE Engine — 便携因果发现工具包 v5

> 基于自回归密度估计 (ΔNLL) + EDM-Takens CCM 交叉验证 + DoWhy 反事实推理的五合一因果发现引擎
>
> **领域专用 · 无需联网 · 即插即用 · 独立移植**

## 五合一因果战队 (Counterfactual Sentai)

```
┌────────┬────────────┬──────────────┬──────────────────────────┐
│ 战士    │ 称号        │ 武器          │ 必杀技                    │
├────────┼────────────┼──────────────┼──────────────────────────┤
│ TRACE  │ 🔴 拓扑先锋  │ 状态空间重构剑  │ 零噪·因果斩 (ΔNLL>8→发现)   │
│ CCM    │ 🔵 流形力场  │ 交叉映射盾      │ 收敛·验证壁 (ρ<3%→震碎)     │
│ EDM    │ 🟡 时序节拍器│ Simplex锁链    │ 套路·探测链 (ρ>0.9→揭露)    │
│ HAVOK  │ ⚫ 混沌暗杀者│ 稀疏强迫匕首    │ 奇点·刺杀 (forcing>5→击破)  │
│ DoWhy  │ 🟡 金·造物主│ do-calculus领域 │ 逻辑崩塌 (ITE≠0→确证)       │
└────────┴────────────┴──────────────┴──────────────────────────┘
合体: 五合一·因果拓扑画像  |  口号: "不是投票，是测绘"
```

## 自洽 CLI — 一键因果分析

```bash
# 最简用法: 指定文本, 自动完成一切
python trrace_cli.py --data my_text.txt

# 指定精度 + 输出名
python trrace_cli.py --data article.txt --preset standard --output my_report

# 五合一完整管线 (需要 DoWhy + causallearn)
cd examples/counterfactual_hybrid
PYTHONIOENCODING=utf-8 python test_case.py

# 真实 TRACE 数据五合一管线
PYTHONIOENCODING=utf-8 python run_real_pipeline.py
```

### 输出

| 文件 | 内容 |
|------|------|
| `{output}.md` | 因果分析报告 (Markdown) |
| `{output}.json` | 结构化数据 (可程序化消费) |
| `{output}_edges.csv` | 因果边列表 (导入 Gephi/NetworkX) |
| `enhanced_dashboard.png` | 四面板因果诊断仪表板 (需五合一模式) |

---

## 环境配置

### 最低要求 (核心 TRACE)

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.10 | |
| PyTorch | >= 2.0 | CUDA 可选, CPU 可降级运行 |
| Transformers | >= 4.40 | 自动检测 LLaMA/GPT-2 架构 |
| SentencePiece | >= 0.2 | BPE 分词器 |
| NumPy | >= 2.0 | |

### 因果推断扩展 (推荐 — 启用五合一 Layer 4-6)

```bash
pip install dowhy networkx pandas statsmodels scikit-learn -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 独立验证 + 可视化 (可选)

```bash
pip install causal-learn graphviz -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> **Graphviz 系统二进制**: Python 包之外还需系统级 `dot` 二进制。
> Windows: https://graphviz.org/download/ → 安装后重启终端。验证: `dot -V`

### 硬件

| 模式 | 最低 | 推荐 |
|------|------|------|
| GPU 推理 | 2GB VRAM | 4GB+ (RTX 3050+) |
| CPU 推理 | 4GB RAM | 8GB+ |

---

## 模型清单

```
TRACE Engine(EDM-Takens CCM)/
│
├── README.md                       ← 本文件
├── SKILL.md                        ← Skill 主入口 (六层防御 + 六维诊断)
├── DESIGN.md                       ← 设计哲学 + 业务场景 + 边界情况
├── trrace_loader.py                ← 统一加载器 (自动适配 LLaMA)
├── trrace_cli.py                   ← 自洽 CLI (一键分析)
├── presets.py                      ← 训练预设系统
│
├── examples/
│   ├── zhihu_consensus/            ← 四合一线案例 (叙事文)
│   │   └── README.md
│   │
│   └── counterfactual_hybrid/      ← ★ 五合一 + DoWhy + Counterfactual
│       ├── README.md               ← DoWhy/反事实概念说明
│       ├── DESIGN_FIVE_IN_ONE.md   ← 五合一工程设计 (600行)
│       ├── counterfactual_bridge.py← TRACE→DoWhy 桥接模块 (v2, 850行)
│       ├── dowhy_auditor.py        ← 9-rule 审计防火墙
│       ├── enhanced_viz.py         ← 4-面板增强仪表板
│       ├── test_case.py            ← 10-项测试套件
│       ├── run_real_pipeline.py    ← 真实数据一键管线
│       └── references/
│           ├── forbidden_rules.md  ← 9 条禁则 + 采纳追踪
│           └── edge_cases.md       ← 7 个文档化边界情况
│
├── Shehui-LLaMA/                   ← 社会/哲学因果模型
│   ├── MODEL_REFERENCE.md
│   ├── model.safetensors      (63 MB)
│   ├── config.json
│   ├── spm.model / spm.vocab
│   └── ...
│
├── Shenji-LLaMA/                   ← 神纪史诗因果模型
│   ├── MODEL_REFERENCE.md
│   ├── model.safetensors      (169 MB)
│   ├── config.json
│   ├── spm.model / spm.vocab
│   └── ...
│
└── references/
    ├── forbidden_rules_reference.md ← EDM-Takens 14 禁则
    ├── edge_cases_reference.md      ← 数据体制缓解策略
    └── research-rigor.md            ← 研究严谨性指南
```

---

## 快速使用

### TRACE 基础调用

```python
from trrace_loader import load_model, trace

model, sp, info = load_model("Shehui-LLaMA")
result = trace(model, sp, "你的文本内容...", threshold=0.5)
# result['edges']: {(i,j): ΔNLL, ...}
# result['tokens']: ["token1", "token2", ...]
```

### 五合一编程 API

```python
import sys
sys.path.insert(0, 'examples/counterfactual_hybrid')
from counterfactual_bridge import quick_analysis
from dowhy_auditor import DoWhyAuditor
from enhanced_viz import render_dashboard

# 一键管线
bridge = quick_analysis(adj_matrix, token_list, threshold=0.5)

# 审计防火墙 (9 条 Forbidden Rules — 对标 edm-takens 14 Secrets)
auditor = DoWhyAuditor(bridge)
report = auditor.audit('full')
report.print_report()
if report.verdict == 'FAIL':
    raise SystemExit("Fix before trusting results")

# 增强仪表板
render_dashboard(bridge, 'outputs/dashboard.png')
```

---

## 算法原理

```
TRACE (Temporal Reconstruction via Autoregressive Causal Estimation)
  1. 自回归模型 = 条件密度估计器 P(x_t | x_{<t})
  2. 掩码干预: 将 history 中的 xi 替换为 <mask>
  3. 因果强度 = NLL_masked - NLL_normal

CCM (Convergent Cross Mapping)
  4. 从 Y 的历史重建 X 的状态 (交叉映射)
  5. 重建精度随样本量收敛 → X causes Y

DoWhy + Counterfactual (Pearl do-calculus)
  6. Model → Identify → Estimate → Refute
  7. Abduction → Action → Prediction (反事实三步)
```

详见: `SKILL.md`, `DESIGN.md`, `DESIGN_FIVE_IN_ONE.md`

---

## 已知局限

1. **领域锁定**: 模型只在训练数据领域有效, 跨域需重新训练
2. **序列长度**: 训练窗口 256 tokens, 长文本需分段分析
3. **DoWhy 图规模**: 精简图模式限制 top-8 边 (可调), 101+ 概念时自动降级
4. **SEM 稳定性**: N < 5×V 时 Pearl 反事实系数有波动 (R3 规则 WARN)
5. **causallearn**: 小样本 (N<200) 时返回 0 边 — 这证明了 TRACE 的不可替代性

---

## 维护

- 训练脚本: `TRACE/scripts/train_shenji_llama.py` (史诗) / `train_shehui_llama.py` (社会)
- 即时训练: `TRACE/scripts/instant_trrace.py` (训练即分析)
- 批量分析: `TRACE/scripts/analyze_truth.py`

---

*最后更新: 2026-07-11 | TRACE Engine v5 (Five-in-One)*
