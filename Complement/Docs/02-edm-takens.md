# edm-takens — EDM 动力学分析核心库

## 概述

EDM（Empirical Dynamic Modeling）+ Takens 嵌入 + HAVOK 分解 + CCM 因果检验的 Python 核心库。
用于分析多变量时间序列的非线性动力学特征。

## 目录结构

```
edm-takens/
├── src/                          # 核心算法（21 个模块）
│   ├── sovereign_havok.py        # HAVOK 分解（核心）
│   ├── pipeline.py               # 管线编排（Layer 1/2/3）
│   ├── enhanced_cross_validate.py # 交叉验证 + 三大守护规则
│   ├── final_interpretation.py   # 最终动力学解释 + 可视化
│   ├── ccm_causality.py          # CCM 因果检验（含收敛斜率）
│   ├── edm_auditor.py            # 数据质量审计（5 档 verdict）
│   ├── data_quality.py           # 数据质量检查
│   ├── edm_adaptive_pipeline.py  # 自适应管线
│   ├── edm_tau_optimization.py   # 时间延迟优化
│   ├── multiview_svd_monitor.py  # 多视图 SVD 监控
│   ├── sensitivity_config.py     # 敏感性配置
│   ├── surrogate_test.py         # 替代数据检验
│   ├── verify_algorithms.py      # 算法验证
│   ├── analysis_profiles.py      # 分析配置档案
│   ├── _edm_bridge.py            # EDM 统一桥接（pyEDM + numpy 回退）
│   ├── _numpy_edm.py             # 纯 numpy EDM 回退实现
│   ├── _paths.py                 # 路径解析
│   ├── _usability.py             # 可用性判定
│   ├── environment_check.py      # 环境检查
│   └── router.py                 # 路由
├── tests/                        # 单元测试
├── examples/                     # 示例
│   ├── game_analysis/            # 游戏数据分析
│   ── yinshen/                  # 隐神 vowel 分析
├── docs/                         # 文档
├── references/                   # 参考资料
├── run_pipeline.py               # CLI 入口
├── run_tests.py                  # 测试入口
├── requirements.txt              # 依赖
├── DESIGN.md                     # 设计文档
└── SKILL.md                      # Skill 说明
```

## 三层架构

### Layer 1: 环境验证
- `sniff_environment()` — 检查 Python 版本、依赖包、文件完整性
- 返回 `ready` / `optional_ready` 状态

### Layer 2: 配置审计 + 自动修正
- `PipelineConfig.auto_correct()` — 6 条自动修正规则：
  1. Hankel 纵横比（p/q >= 10）
  2. SG 窗口上限（p//4）
  3. 嵌入维度上限（N/5）
  4. tau 自动计算
  5. 二值目标建议
  6. 小样本顾问提示（N<30）

### Layer 3: 算法交叉验证
- `run_enhanced_validation()` — 三大守护规则：
  - Safeguard 1: Lyapunov 预测视界
  - Safeguard 2: CCM 受害者镜像原则
  - Safeguard 3: Hankel 纵横比

## 核心算法

### HAVOK 分解（sovereign_havok.py）
- 基于 Hankel 矩阵的 SVD 分解
- 提取动力学 forcing 项
- `degenerate` 短路保护（近常量信号）
- 稳定性分类：`classify_havok_stability()`

### CCM 因果检验（ccm_causality.py）
- 收敛斜率检验（不仅看最终 rho 值）
- 受害者镜像原则验证
- 共同驱动因素免责声明

### EDM 预测（_edm_bridge.py）
- 优先使用 pyEDM（C++ 后端）
- 回退到纯 numpy/scipy 实现
- `EmbedDimension` / `Simplex` / `SMap` 统一接口

## 样本量处理

| N 范围 | 行为 |
|--------|------|
| N < 10 | 硬阻止，返回 `insufficient_samples` 友好错误 |
| 10 <= N < 30 | 警告但继续，maxE 限制为 N//5 |
| N >= 30 | 正常流程 |

## CLI 用法

```bash
# 完整分析
python run_pipeline.py --data data/game_log.csv --target result

# 仅环境报告
python run_pipeline.py --report-only

# 自动修正
python run_pipeline.py --auto-fix
```

## 依赖

```
numpy>=1.21
scipy>=1.7
pandas>=1.3
matplotlib>=3.4
pyEDM>=1.17 (可选，有 numpy 回退)
```
