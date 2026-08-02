# 游戏数据 — EDM-Takens Skill 案例

32 场游戏, 4 个变量 (result/kills/deaths/damage), 二元目标。
**Skill 的基准连续-二元混合案例**, 与音神案例 (类别数据) 互补。

## 数据

| 属性 | 值 |
|------|-----|
| 样本数 N | 32 |
| 变量 | result(二元), kills, deaths, damage |
| 目标 | result (win/loss) |
| 关键挑战 | N<50, 二元目标, Hankel 比紧张 |

## 运行

```bash
cd .skills/edm-takens
python examples/game_analysis/run_analysis.py
```

## 激活的 14 条规则

| 规则 | 状态 | 说明 |
|------|------|------|
| S3 Hankel | ★★★★ | N=32 时 E>3 进入危险区 — AUTO-FIX |
| S8 Stationarity | ★★★★ | ADF+KPSS 联合检验 |
| S9 Genericity | ★★★ | 二元目标 — ρ 天花板 ~0.87 |
| S4 Multiview | ★★★ | N<100 且 K=4 → 强烈推荐 |
| S1 Lyapunov | [D] | N<100 — surrogate 替代下限 |
| S6 EDM-HAVOK | [D] | 交叉验证 |
| S11 Common Driver | [I] | CCM 免责 — "团队实力"可能为公共驱动 |

## 目录

```
examples/game_analysis/
├── README.md                  ← 本文件
├── run_analysis.py            ← 主分析脚本
├── game_report.md             ← 分析报告 (自动生成)
├── data/
│   ├── game_log.csv           ← 32 场游戏
│   └── template.csv           ← 多变量数据模板
├── figures/
│   └── game_dashboard.png     ← 综合分析面板
└── archive/                   ← 历史文件
    ├── demo.py
    ├── phonon_v3.py
    └── combined_100.csv
```
