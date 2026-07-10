# EDM-Takens + SovereignHAVOK Skill

> 面向非线性时间序列的**动力系统分析工具包**。吸引子重构、预测、因果推断与 Koopman 分解一体化，内置“14 条禁忌规则”的执行前防火墙，按数据画像智能分流。

---

## 一句话定位

EDM-Takens + SovereignHAVOK Skill 将 **Takens 嵌入定理**、**经验动态建模（EDM）** 和 **HAVOK（Koopman 算子）** 封装为可复用的三层纵深防御管线，适用于游戏、生态、金融、物理等非线性时间序列场景。N<50 甚至 N<20 都可运行——但 Skill 会诚实地告诉你什么时候不该信任结果。

---

## 核心能力

| 能力 | 说明 | 对应模块 |
|------|------|----------|
| **吸引子重构** | 延迟嵌入把一维时间序列还原到高维流形 | `sovereign_havok.py` |
| **非线性预测** | Simplex/S-Map —— 在流形上找近邻 | `_numpy_edm.py` / `_edm_bridge.py` |
| **收敛式因果推断** | CCM + 收敛斜率 + 纯噪声防御 (Round 11) | `ccm_causality.py` |
| **HAVOK 分解** | Koopman 线性自治 + 间歇性强迫项 | `sovereign_havok.py` (含 S14 采样充分性) |
| **交叉验证** | EDM 与 HAVOK 互相验证 (S6) | `enhanced_cross_validate.py` |
| **多视角嵌入** | N<100 多变量时用空间嵌入替代时间延迟 (S4) | `multiview_svd_monitor.py` |
| **SVD 残差监控** | 检测吸引子变形/概念漂移 (S5) | `multiview_svd_monitor.py` |
| **代理数据检验** | IAAFT + 端点匹配，区分非线性与随机 | `surrogate_test.py` |
| **多重比较校正** | CCM 批量测试的 FDR/Bonferroni 校正 (S13) | `ccm_causality.py:ccm_batch_test` |
| **公共驱动免责** | 所有 CCM 输出自动附带动力学耦合≠机制因果声明 (S11) | `ccm_causality.py:common_driver_disclaimer` |

---

## 为什么选它

- **14 条禁忌规则，非 7 条**：从 Lyapunov 视界 (S1) 到采样充分性 (S14)，每条都有文献溯源 `[C][D][E]` 标注。详见 `references/forbidden_rules_reference.md`。
- **三层纵深防御**：Layer 1 环境验证 → Layer 2 配置审计 (S2/S3/S7/S8/S9 前置关卡) → Layer 3 算法交叉验证 (S6/S1/S10/S12/S14)，失败更快。
- **分流不溢出**：14 条规则不是全部激活。Router 按数据画像 (N, K, 二元, 分析目标) 选择性加载规则子集，避免 AI Skill 上下文溢出。
- **单点真理**：CCM 因果判定 (`ccm_causality.py`) 和 HAVOK 稳定性分级 (`classify_havok_stability`) 都是单一函数，所有模块通过薄包装调用。
- **pyEDM + NumPy 兜底**：优先 pyEDM，缺失时自动回落到纯 NumPy/SciPy (`_edm_bridge.py`)。
- **小样本友好**：N<100 提示 Multiview；N<50 限制嵌入维度；Hankel p/q 不足直接 FAIL + AUTO-FIX。
- **研究可追溯**：自动 config artifact、E±1 敏感扫描、探索性/验证性标注 (research-rigor.md)。

---

## 快速开始

### 1. 解包与安装

```bash
python -m zipfile -e edm-takens.skill .
cd edm-takens
pip install -r requirements.txt
```

### 2. 运行案例

两个自包含案例各有 `run_analysis.py`，直接运行：

```bash
# 基准案例：32 场游戏 (连续+二元混合)
python examples/game_analysis/run_analysis.py

# 边界案例：120 音素序列 (类别数据)
python examples/yinshen/run_analysis.py
```

### 3. 通用 CLI

```bash
python run_pipeline.py --data your_data.csv --target result --auto-fix
```

### 4. 运行测试

```bash
python run_tests.py          # 完整测试
python run_tests.py --quick  # 快速测试
```

---

## 十四项禁忌规则速览

| # | 规则 | 性质 | 权重 | 核心处置 |
|---|------|------|------|---------|
| S1 | Lyapunov 视界 | [D] | ★★★ | 预测 > 5τ_L → FAIL |
| S2 | CCM 受害者镜像 | [G] | ★★★ | 双向 CCM + 收敛斜率 |
| S3 | Hankel 黄金比例 | [G] | ★★★★ | p/q < 3 → FAIL 阻断 + AUTO-FIX |
| S4 | Multiview 嵌入 | [D] | ★★★ | N<100 且 K≥2 → 强烈推荐 |
| S5 | SVD 残差监控 | [D] | ★★★ | 残差 > 2.5× 基线 → FAIL |
| S6 | EDM-HAVOK 交叉验证 | [D] | ★★★ | DISCREPANCY → WARN |
| S7 | CCM 箭头陷阱 | [I] | ★★★ | 自动化管线双向量化 |
| S8 | 平稳性关卡 | [G] | ★★★★ | ADF+KPSS 联合决策矩阵 |
| S9 | 观测泛型性 | [G] | ★★★ | 类别数据/饱和/量化检测 |
| S10 | 周期混淆 | [D] | ★★ | P_dom > 30% → CCM 歧义警告 |
| S11 | 公共驱动免责 | [I] | ★★ | 所有 CCM 输出强制追加 |
| S12 | 预测衰减剖面 | [D] | ★ | Tp 扫描 → 衰减形状分类 |
| S13 | 多重比较校正 | [I] | ★★ | CCM batch_test + FDR/Bonferroni |
| S14 | 采样充分性 | [D] | ★ | HAVOK 尖峰宽度审计 |

完整定义、数值溯源、文献引用: `references/forbidden_rules_reference.md` (1128 行)
配套文献目录: `references/fourteen_rules_bibliography.md` (39 篇论文)

---

## 文件结构

```
edm-takens/
├── SKILL.md                          ← 主入口文档
├── DESIGN.md                         ← 架构设计哲学
├── secret_adoption_audit.md          ← 14 条规则采纳审计
├── requirements.txt / -lock.txt
├── run_tests.py                      ← 测试入口
├── src/                              ← 17 个 Python 模块
│   ├── edm_auditor.py                ← 14-secret 防火墙
│   ├── ccm_causality.py              ← CCM 唯一真相源 (+S11/S13)
│   ├── sovereign_havok.py            ← HAVOK 引擎 (+S14)
│   ├── router.py                     ← 数据画像分流引擎
│   ├── pipeline.py                   ← 统一管线
│   └── ...
├── tests/                            ← 2 个测试文件
├── examples/                         ← 自包含案例
│   ├── game_analysis/                ← 32 场游戏 (基准案例)
│   └── yinshen/                      ← 120 音素 (边界案例)
├── references/                       ← 5 个方法论参考
│   ├── forbidden_rules_reference.md  ← 14 规则 + 数值溯源
│   └── fourteen_rules_bibliography.md← 39 篇论文目录
└── docs/                             ← 7 个工程附件
    ├── CHANGELOG.md
    └── thresholds_and_heuristics.md
```

---

## 学术基础

- **Takens Embedding Theorem**: Takens, F. (1981). LNM, 898.
- **CCM**: Sugihara et al. (2012). *Science*, 338, 496-500.
- **CCM Convergence**: Cobey & Baskerville (2016). *Nature Comms*, 7, 12891.
- **Multiview**: Sugihara et al. (2016). *Science*, 353, 922-925.
- **HAVOK**: Brunton et al. (2017). *Nature Comms*, 8, 19.
- **Stationarity**: Schreiber (1997). *PRL*, 78(5); Kennel (1997). *PRE*, 56(1).
- **FDR**: Benjamini & Hochberg (1995). *JRSS-B*, 57(1).
- **Sampling**: Eckmann & Ruelle (1985). *Rev. Mod. Phys.*, 57(3); Gibson et al. (1992). *Physica D*.

完整 39 篇论文见 `references/fourteen_rules_bibliography.md`。

---

## 获取帮助

- 设计哲学: `DESIGN.md`
- 工程审计: `docs/edm-takens_skill_audit.md`
- 变更日志: `docs/CHANGELOG.md`
- 阈值与启发式: `docs/thresholds_and_heuristics.md`
- 案例: `examples/game_analysis/README.md` / `examples/yinshen/README.md`
