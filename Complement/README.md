# Complement — EDM-Takens Skill

非线性动力系统经验动态建模与 HAVOK 分析技能包。

## 交付内容

| 文件 | 格式 | 大小 | 用途 |
|------|------|------|------|
| `edm-takens/` | 目录（30 文件） | — | 直接使用、git 版本控制 |
| `edm-takens.skill` | ZIP 包 | 110 KB | WorkBuddy 一键安装 |

## 技能概要

```
SKILL.md            ← 主入口：文件地图、7 条秘密、决策指南、数据就绪路由
DESIGN.md           ← 三层防御架构设计哲学
secret_adoption_audit.md  ← 7 条秘密逐一评估：采纳/延期/弃用

src/ (16 模块)
├── sovereign_havok.py          ← HAVOK 核心引擎（V 基回归 + SG 导数 + 自适应 SVD）
├── edm_auditor.py              ← 防火墙：7 条秘密预执行审计（PASS/WARN/FAIL）
├── router.py                    ← 数据路由引擎：分级→目标→自动执行（6 场景）
├── pipeline.py                  ← 统一管道 + 自动修正
├── environment_check.py         ← 环境验证器（17 项完整性检查）
├── edm_tau_optimization.py      ← 互信息法最优 τ
├── edm_adaptive_pipeline.py     ← τ→E→θ→CCM 自适应流水线
├── enhanced_cross_validate.py   ← EDM-HAVOK 交叉验证
├── verify_algorithms.py         ← 5 级 100 分评分
├── final_interpretation.py      ← 游戏数据动力学诊断
├── multiview_svd_monitor.py     ← Secret 4 (Multiview) + Secret 5 (SVD 残差监控)
├── sensitivity_config.py        ← 配置捕获 + 敏感性扫描（E±1）
├── surrogate_test.py            ← IAAFT 替代数据统计检验
├── _paths.py                    ← 可移植路径解析
├── edm_havok_integration.py     ← [DEPRECATED] 已废弃，保留仅供历史参考
└── __init__.py

references/ (4 篇)
├── takens_embedding_reference.md  ← 数学基础
├── forbidden_rules_reference.md   ← 七条禁忌规则（完整论述）
├── edge_cases_reference.md        ← 数据场景缓解措施
└── research-rigor.md              ← 研究健全性（预注册、配置、敏感性、控制）

tests/ (2 文件), examples/ (1 文件), data/ (2 文件)
```

## 状态

| 检查项 | 结果 |
|--------|------|
| 文件完整性（源端 = 目标端） | 30/30 byte-identical |
| 编码一致性 | 全部 UTF-8 |
| SKILL.md 文件地图 | 16 模块全部列出 |
| 代码→文档交叉引用 | 全部解析（4/4） |
| Import 依赖链 | 零循环依赖 |
| 环境验证覆盖 | 17 项（跳过废弃模块） |
| .skill 包 | 30 条目精确匹配 |

**版本**: 审计基准 2026-07-07

## 安装

WorkBuddy 中通过 .skill 包安装，或将 `edm-takens/` 目录放置于 `.skills/` 下。

## 依赖

```
numpy, scipy, pandas, matplotlib, pyEDM (2.5.0), scikit-learn
```

详见 `requirements.txt`（版本锁定）。
