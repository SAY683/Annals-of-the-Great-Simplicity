# 音神序列 — EDM-Takens Skill 案例

10 行咒语 × 12 字 = 120 个音素序列，按韵尾分为六姬（太/玄/美/希/祈/妙），拆解为基础辅音/元音。

## 数据

| 属性 | 值 |
|------|-----|
| 样本数 N | 120 |
| 变量 | 六姬(6类) / 主元音(5类) / 主辅音(18类) |
| 类型 | 类别数据的整数编码 — S9 泛型性关卡在此触发 |
| 结构 | 四字为组 — 存在弱 4 步周期性 (S10 检测) |

## 运行

```bash
cd .skills/edm-takens
python examples/yinshen/run_analysis.py       # 需要 edm_env2 虚拟环境 (pyEDM, scipy, pandas, pypinyin)
```

## 激活的 14 条规则

| 规则 | 权重 | 结果 |
|------|------|------|
| S3 Hankel 比 | ★★★★ | PASS — p/q ≥ 14 |
| S8 平稳性 | ★★★★ | PASS — ADF+KPSS 确认平稳 |
| S9 泛型性 | ★★★ | WARN — 六姬/元音触发量化粗糙 |
| S1 Lyapunov | [D] | τ_L ≈ 11–15 步, 3τ_L ≈ 35–46 |
| S6 EDM-HAVOK | [D] | DISCREPANCY — EDM 非线性 vs HAVOK 近高斯 |
| S10 周期性 | [D] | 四字结构功率仅 2.5% (未触发 30% 阈值) |
| S11 公共驱动 | [I] | 每 CCM 附带免责声明 |
| S14 采样 | [D] | 尖峰 ≤2 采样点 (类别数据预期行为) |
| S2/S7 CCM | ★★★ | 双向测试；E 与 EmbedDimension 一致 |

## 关键发现

**CCM 嵌入维一致性**: 原始分析用 E=2 报告 lag-1 强收敛 (ρ≈0.99)，但使用 EmbedDimension
最优 E (6/6/4) 后，CCM 未检测到收敛因果连接。这直接验证了 S2 的设计——CCM 嵌入维
必须与 EmbedDimension 一致，否则欠嵌入可产生虚假收敛。

**EDM-HAVOK 分歧**: 六姬和元音序列 EDM 判定非线性，但 HAVOK 峰度为亚高斯
(-0.66 / -0.16)。这种 DISCREPANCY 本身是诊断信号——提示非线性结构可能弱于
EDM 单侧视角所暗示的。辅音序列双方一致认为近线性。

## 目录

```
examples/yinshen/
├── README.md                  ← 本文件
├── run_analysis.py            ← 主分析脚本 (遵循 14 条规则, 三层纵深防御)
├── yinshen_report.md          ← 分析报告 (自动生成)
├── yinshen_report.json        ← 结构化数据 (自动生成)
├── data/
│   ├── yinshen_wide.csv       ← 完整音素 one-hot (120 行 × 40 列)
│   └── yinshen_ji_vowel.csv   ← 四字组 + 姬分类
├── figures/
│   └── yinshen_dashboard.png  ← 综合分析面板 (5 列 × 3 行, 自动生成)
└── reference/                 ← 原始分析存档 (未遵循 14 条规则, 仅供参考)
    ├── yinshen_edm_analysis.py
    └── reports/
```
