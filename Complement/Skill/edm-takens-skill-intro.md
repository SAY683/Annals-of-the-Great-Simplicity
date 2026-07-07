# EDM-Takens + SovereignHAVOK Skill

> 一个面向非线性时间序列的**动力系统分析工具包**：吸引子重构、预测、因果推断与 Koopman 分解一体化，内置“执行前防火墙”自动拦截常见误用。

---

## 一句话定位

EDM-Takens + SovereignHAVOK Skill 把 **Takens 嵌入定理**、**经验动态建模（EDM）** 和 **HAVOK（Hankel 替代视角的 Koopman）** 三种方法封装成可复用的分析流程，适用于游戏、生态、金融、物理等任何非线性时间序列场景。

---

## 核心能力

| 能力 | 说明 | 对应模块 |
|------|------|----------|
| **吸引子重构** | 通过延迟嵌入把一维时间序列还原到高维流形 | `sovereign_havok.py` |
| **非线性预测** | Simplex / S-Map 投影，预测不是回归，而是“在流形上找近邻” | `_numpy_edm.py` / `_edm_bridge.py` |
| **收敛式因果推断** | CCM（Convergent Cross Mapping）+ 收敛斜率检验，避免“高 rho 假阳性” | `ccm_causality.py` |
| **HAVOK 分解** | 把复杂动力学拆成“线性自治部分 + 间歇性强迫项”，输出 Koopman 特征值与强迫峰度 | `sovereign_havok.py` |
| **交叉验证** | EDM 与 HAVOK 互相验证，区分“何时发生（IF）”与“何时驱动（WHEN）” | `enhanced_cross_validate.py` |
| **多视角嵌入** | 小样本（N<100）下用多变量组合提升嵌入质量 | `multiview_svd_monitor.py` |
| **SVD 残差监控** | 检测吸引子结构漂移/概念漂移 | `multiview_svd_monitor.py` |
| **代理数据检验** | IAAFT 代理数据 + 端点匹配，区分非线性信号与随机过程 | `surrogate_test.py` |

---

## 为什么选它

- **先审计，再计算**：`edm_auditor.py` 在执行任何昂贵计算前检查 7 条“禁忌规则”（Lyapunov Horizon、CCM Victim Mirror、Hankel 黄金比、Multiview、SVD 监控、交叉验证、Arrow Trap），避免配置错误导致错误结论。
- **单点真理**：CCM 因果判定和 HAVOK 稳定性分级都集中到一个函数，避免不同模块结论自相矛盾。
- **pyEDM 兼容 + 纯 NumPy 兜底**：优先使用 `pyEDM`，缺失时自动回落到自研 NumPy/SciPy 实现，保证可运行性。
- **小样本友好**：N<100 自动提示使用 Multiview；N<50 自动限制嵌入维度；Hankel 矩阵比例不足直接 FAIL。
- **研究可追溯**：自动保存配置产物（config artifact），支持 E±1 敏感性扫描，符合可重复研究规范。

---

## 快速开始

### 1. 安装与验证

```bash
# 解压 skill 包
python -m zipfile -e edm-takens.skill .

# 安装依赖
cd edm-takens
pip install -r requirements.txt

# 验证环境
python -c "from environment_check import validate_environment; \
           assert validate_environment().ready"
```

### 2. 最小工作示例

```python
import sys
sys.path.insert(0, 'edm-takens/src')

import pandas as pd
from edm_auditor import audit_pipeline
from sovereign_havok import SovereignHAVOK
from final_interpretation import ccm_with_convergence

# 读取数据
df = pd.read_csv('edm-takens/data/game_log.csv')

# 1. 先审计
target = 'result'
audit = audit_pipeline(n=len(df), E=3, target_col=target,
                       columns=list(df.columns), is_binary=True)
audit.print_report()

# 2. HAVOK 分解
sh = SovereignHAVOK(q_delays=3).fit(df[target].values)
print(sh.report())

# 3. CCM 因果推断（kills 是否驱动 result）
result = ccm_with_convergence(df, 'kills', 'result', E=3)
print(result['verdict'])
```

### 3. 运行统一管线

```python
from pipeline import run_pipeline, PipelineConfig

config = PipelineConfig(
    data_path='edm-takens/data/game_log.csv',
    target_col='result',
    columns=['kills', 'damage', 'deaths', 'result']
)
result = run_pipeline(config, auto_fix=True)
```

### 4. 运行测试

```bash
python run_tests.py          # 完整测试
python run_tests.py --quick  # 快速测试（跳过慢模块）
```

---

## 典型决策流程

拿到一个时间序列，按以下顺序决策：

```
数据长度 N 是多少？
├── N < 30  →  不建议 EDM/CCM；考虑更大样本或贝叶斯方法
├── N 30–100  →  EDM 预测 + CCM（带收敛检查）；多变量时启用 Multiview
├── N > 100  →  完整流程：HAVOK + EDM + 交叉验证 + Lyapunov 估计

目标类型？
├── 连续变量  →  Simplex / S-Map / HAVOK 直接可用
├── 二元/离散  →  在驱动变量上运行 EDM/HAVOK，对二元目标解释 rho 上限

是否关注因果？
├── 是  →  必须做双向 CCM + 收敛检查（ccm_causality.py）
├── 否  →  预测任务优先用 EDM 或 HAVOK

是否在线监控？
└── 是  →  SVDResidualMonitor 滑动窗口残差监控
```

---

## 七条执行前安全检查（Secrets）

| # | 规则 | 作用 |
|---|------|------|
| 1 | **Lyapunov Horizon** | 数据长度不足时不下 Lyapunov 指数结论 |
| 2 | **CCM Victim Mirror + Arrow Trap** | 双向 CCM + 收敛斜率，防止“高 rho 假阳性” |
| 3 | **Hankel Golden Ratio** | 强制 Hankel 行数 p 与延迟 q 比例合理，避免数值退化 |
| 4 | **Multiview Embedding** | 小样本多变量时优先使用空间信息 |
| 5 | **SVD Residual Monitor** | 监控吸引子结构漂移 |
| 6 | **EDM-HAVOK Cross-Validation** | 两种方法互验，避免单一方法偏见 |
| 7 | **CCM Arrow Trap** | 防止把“被驱动变量”误判为“驱动变量” |

防火墙状态：5/7 完全采用，1 项部分采用（受环境限制），1 项推迟（数据长度不足时）。详情见 `secret_adoption_audit.md`。

---

## 文件结构速览

```
edm-takens/
├── SKILL.md                  # 主入口文档
├── requirements.txt          # 依赖
├── requirements-lock.txt     # 锁定版本（可复现）
├── run_tests.py              # 测试入口
├── src/                      # 17 个 Python 模块
│   ├── ccm_causality.py          # 规范化 CCM 因果测试
│   ├── sovereign_havok.py        # HAVOK 核心引擎
│   ├── edm_auditor.py            # 执行前防火墙
│   ├── enhanced_cross_validate.py # EDM-HAVOK 交叉验证
│   ├── pipeline.py               # 统一管线
│   └── ...
├── tests/                    # 单元测试
├── examples/                 # 演示脚本
├── data/                     # 示例数据（game_log.csv）
├── references/               # 方法论与禁忌规则参考
└── docs/                     # 工程审计与变更日志
```

---

## 常见陷阱与规避

| 陷阱 | 表现 | 解决方案 |
|------|------|----------|
| 用 CCM 看单点 rho | 把同步/共因误判为因果 | 检查收敛斜率 + Spearman |
| 小样本硬上高维嵌入 | 过拟合噪声结构 | 启用 Multiview，限制 E <= N/5 |
| 非周期数据直接 IAAFT | 端点跳变污染代理 kurtosis | 已内置端点匹配（Theiler & Prichard 1996） |
| 把 HAVOK 输出当预测 | 它解释结构，不是预测模型 | 与 EDM 交叉验证，明确区分解释/预测 |
| 近恒定输入 | explained_var 变成 NaN | 已显式处理为 0.0 并报警 |

---

## 适用场景示例

- **游戏分析**：判断“击杀数”是否真正驱动“比赛结果”，而非两者都被某个隐藏变量同步。
- **生态研究**：捕食者与猎物数量之间的因果方向。
- **金融**：识别非线性因果驱动关系，但需满足数据长度与平稳性要求。
- **物理/工程**：从单变量测量中恢复 Koopman 算子与间歇性强迫项。

---

## 学术基础

- **Takens Embedding Theorem**: Takens, F. (1981). *Detecting strange attractors in turbulence.* Lecture Notes in Mathematics, 898.
- **CCM**: Sugihara, G. et al. (2012). *Detecting causality in complex ecosystems.* Science, 338, 496-500.
- **HAVOK**: Brunton, S.L. et al. (2017). *Chaos as an intermittently forced linear system.* Nature Communications.

---

## 获取帮助

- 详细文档：`SKILL.md`、`DESIGN.md`
- 审计记录：`docs/edm-takens_skill_audit.md`
- 变更日志：`docs/CHANGELOG.md`
- 阈值与启发式：`docs/thresholds_and_heuristics.md`
