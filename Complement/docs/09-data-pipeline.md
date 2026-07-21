# 数据流转、文件格式与分析流程

## 1. 数据格式

### 输入：CSV 时间序列

EDM 分析要求 CSV 格式的时间序列数据：

```csv
timestamp,result,kills,damage,deaths,total_ms,z_pca_1
2024-01-01,1,5,120,2,3500,0.123
2024-01-02,0,3,80,1,2800,-0.456
...
```

**要求**：
- 至少 30 行数据（理想 >= 50）
- 数值列（非字符串）
- 无缺失值（NaN/Inf 会被自动处理但影响结果）
- 第一列通常为时间戳或索引

### 输入：文本语料（TRACE 分析）

```
你的因果分析文本内容...
可以是多段落、多句子。
TRACE 会提取概念并构建因果图。
```

### 输出：分析结果

每个任务在 `results/{timestamp}_{job_id}/` 目录下生成：

```
results/1784622252_78302d20/
├── config_{timestamp}.json      # 分析配置
├── enhanced_cross_validation.png # 交叉验证图
└── dynamics_interpretation.png   # 动力学解释图（可选）
```

### 输出：JSON 摘要

任务完成后返回 JSON 结构：

```json
{
  "success": true,
  "filename": "game_log.csv",
  "target_col": "result",
  "variables": ["result", "kills", "damage"],
  "summary": {
    "pipeline": {
      "n_samples": 15,
      "n_variables": 6,
      "E": 2,
      "tau": 1,
      "error": null
    },
    "havok": {
      "rank": 2,
      "explained_variance": 0.766,
      "regression_r2": 0.524,
      "kurtosis": -0.988,
      "max_eigenvalue": null,
      "stability_tier": "N/A (degenerate HAVOK)",
      "is_degenerate": true
    },
    "cross_validation": { ... },
    "interpretation": { ... }
  },
  "task_id": "1784622252_78302d20",
  "images": ["enhanced_cross_validation.png"]
}
```

## 2. 分析流程详解

### EDM 分析三阶段

```
Stage 1: run_pipeline()
├── Layer 1: 环境验证
├── Layer 2: 配置审计 + 自动修正
│   ├── Rule 1: Hankel 纵横比（p/q >= 10）
│   ├── Rule 2: SG 窗口上限（p//4）
│   ├── Rule 3: 嵌入维度上限（N/5）
│   ├── Rule 4: tau 自动计算
│   ├── Rule 5: 二值目标建议
│   └── Rule 6: 小样本顾问提示
└── Layer 3: 算法执行
    ├── EmbedDimension 自动检测 E
    ├── SovereignHAVOK 分解
    ├── Simplex 预测
    └── SMap 非线性预测

Stage 2: run_enhanced_validation()
├── Safeguard 1: Lyapunov 预测视界
├── Safeguard 2: CCM 受害者镜像原则
└── Safeguard 3: Hankel 纵横比

Stage 3: interpret_game_data()
├── Phase 1: 单变量动力学分析
├── Phase 2: CCM 因果方向分析
└── Phase 3: 综合解释 + 可视化
```

### TRACE 分析流程

```
文本输入
    │
    ├── LIGHT 模式
    │   └── jieba 分词 → 概念图 → 简化流程
    │
    ├── DEEP 模式
    │   ├── jieba 分词 → 概念图
    │   ── 六战士完整诊断
    │       ├── DoWhy 适配
    │       ├── causal-learn 验证
    │       ├── 复合诊断
    │       ├── 反事实桥接
    │       ├── 可复现仪表板
    │       └── 六面板可视化
    │
    └── SUPER 模式
        ├── LLaMA Worker 加载模型
        ├── token-level TRACE 因果发现
        │   ├── 滑动窗口分割
        │   ├── token 过滤
        │   └── 因果边提取
        └── 六战士完整诊断
```

### 桥接流程（trace-to-edm）

```
TRACE 输出（概念矩阵）
    │
    ├── Layer 1: 元数据 SCM
    │   ├── 结构化概念矩阵
    │   ├── 提取时间序列元数据
    │   └── 构建 SCM 框架
    │
    ├── Layer 2: 语义层
    │   ├── 语义概念映射
    │   ├── 变量关系推断
    │   ── 时间序列对齐
    │
    ├── Layer 3: 神圣文本层
    │   ├── 特殊文本格式处理
    │   ├── 叙事元数据提取
    │   └── 轨迹数据生成
    │
    ├── csv_builder.py
    │   └── 构建 CSV 时间序列
    │
    ├── dataset_manager.py
    │   └── 数据集管理 + 导出
    │
    └── edm_trigger.py
        └── POST /api/analyze/jobs → edm-takens-web
```

## 3. 关键参数说明

### EDM 参数

| 参数 | 说明 | 默认值 | 范围 |
|------|------|--------|------|
| `q` | 嵌入维度（Hankel 矩阵列数） | 自动检测 | 2 - N/5 |
| `tau` | 时间延迟 | 自动计算 | 1 - N/3 |
| `max_E` | EmbedDimension 搜索上限 | 8 | 2 - N/5 |
| `energy_threshold` | SVD 能量阈值 | 0.99 | 0.9 - 0.99 |
| `window_length` | Savitzky-Golay 窗口 | 11 | 5 - p//4 |
| `auto_fix` | 自动修正 | false | true/false |

### TRACE 参数（presets.yaml）

| 参数 | 说明 | 默认值 | 范围 |
|------|------|--------|------|
| `threshold` | 因果边显著性阈值 | 0.01 | 0.001 - 0.1 |
| `window_size` | 滑动窗口大小 | 128 | 2 - 256 |
| `max_segments` | 最大分段数 | 3 | 1 - 10 |
| `min_valid_tokens` | 最小有效 token 数 | 10 | 5 - 50 |
| `max_edges_for_dowhy` | DoWhy 最大边数 | 20 | 5 - 50 |
| `filter_mode` | 过滤模式 | topn | topn / percentile |
| `filter_percentile` | 过滤百分位 | 95 | 50 - 99 |
| `classical_mode` | 古典模式（保留虚词） | false | true/false |

## 4. 结果解读

### HAVOK 稳定性分类

| 等级 | max_eigenvalue | 说明 |
|------|----------------|------|
| STABLE | < 0.5 | 稳定动力学 |
| MARGINALLY_STABLE | 0.5 - 0.8 | 边际稳定 |
| UNSTABLE | 0.8 - 1.0 | 不稳定 |
| CHAOTIC | > 1.0 | 混沌 |
| N/A | null | 退化（样本不足/近常量） |

### CCM 因果方向

```
Rule: To test X→Y, build M_Y (effect's manifold), predict X (cause).
"The victim (Y) bears the imprint of the perpetrator (X)."

结果示例：
  kills → result: rho=0.65, convergence_slope=0.023 [SIGNIFICANT]
  damage → result: rho=0.42, convergence_slope=0.008 [WEAK]
  deaths → result: rho=0.31, convergence_slope=-0.005 [NO CAUSALITY]
```

### Hankel 纵横比

| p/q 范围 | 状态 | 说明 |
|----------|------|------|
| >= 10 | PASS | SVD 数值稳定 |
| 5 - 10 | WARN | 可接受但非最优 |
| < 5 | CRITICAL | SVD 数值退化 |

### Lyapunov 指数

| lambda_max | 说明 |
|------------|------|
| > 0 | 混沌系统（正 Lyapunov 指数） |
| = 0 | 周期/准周期系统 |
| < 0 | 稳定系统（收敛到吸引子） |
| null | 估计不可靠（样本不足） |

## 5. 数据质量检查

### 自动检查项

1. **非有限值**：Inf/NaN 检测与处理
2. **样本量**：N < 10 硬阻止，10-30 警告
3. **Hankel 纵横比**：p/q >= 10 为优
4. **二值目标**：EDM rho 上限 ~0.87
5. **近常量信号**：HAVOK degenerate 检测
6. **共线性**：变量间高相关性警告

### 审计 Verdict（5 档）

| Verdict | 说明 | 行动 |
|---------|------|------|
| PASS | 所有检查通过 | 正常分析 |
| PASS_WITH_NOTES | 通过但有建议 | 正常分析，参考建议 |
| WARN | 存在警告 | 可继续，结果需谨慎解读 |
| FAIL | 存在严重问题 | 建议修正后重试 |
| BLOCKED | 无法分析 | 必须修正（如 N<10） |
