# trace-engine — 因果发现引擎

## 概述

基于 TRACE（Temporal Recurrent Attention Causal Engine）框架的因果推断引擎，
集成 LLaMA 语言模型进行 token-level 因果发现，配合六战士（Six Warriors）诊断体系。

## 目录结构

```
trace-engine/
├── examples/counterfactual_hybrid/   # 核心分析模块
│   ├── six_warriors.py               # 六战士诊断
│   ├── counterfactual_bridge.py      # TRACE → DoWhy 桥接
│   ├── dowhy_adapter.py              # DoWhy 1.4 适配器
│   ├── dowhy_auditor.py              # DoWhy 审计
│   ├── pearl_counterfactual.py       # Pearl 反事实推理
│   ├── causallearn_validator.py      # causal-learn 验证
│   ├── compound_diagnostic.py        # 复合诊断
│   ├── enhanced_viz.py               # 增强可视化
│   ├── six_panel_viz.py              # 六面板可视化
│   ├── repro_dashboard.py            # 可复现仪表板
│   ├── presets.py                    # 参数预设
│   ├── presets.yaml                  # 预设配置（YAML）
│   ├── _config.py                    # 配置（模型路径探测）
│   ├── _logging.py                   # 日志
│   ├── _token_filters.py             # Token 过滤器
│   ├── _causallearn_utils.py         # causal-learn 工具
│   ├── pipeline_helpers.py           # 管线辅助
│   ├── project_paths.py              # 项目路径
│   ├── simulation_model.py           # 模拟模型
│   ├── test_case.py                  # 测试用例
│   ├── minimal_dataframe.py          # 最小数据框
│   ├── run_cli.py                    # CLI 入口
│   └── run_real_pipeline.py          # 真实管线入口
├── models/                           # LLaMA 模型
│   ├── shehui-llama/                 # 社会模型（27M）
│   ├── shenji-llama/                 # 神纪模型（469M）
│   └── shehui-llama-v4-archive/      # 归档模型（470M）
├── references/                       # 参考资料
├── tests/                            # 单元测试
├── date/                             # 训练/测试数据
├── health_check.py                   # 健康检查
├── build_bridge_schema.py            # 构建桥接 Schema
├── requirements.txt
├── DESIGN.md
└── SKILL.md
```

## 三种分析模式

| 模式 | 说明 | 耗时 | 依赖 |
|------|------|------|------|
| **LIGHT** | jieba 概念图 + 简化流程 | 1-3 秒 | jieba |
| **DEEP** | jieba 概念图 + 完整六战士诊断 | 10-60 秒 | jieba + dowhy |
| **SUPER** | LLaMA 模型 token-level TRACE + 完整诊断 | 视文本长度 | LLaMA 模型 |

## 六战士诊断体系

六个独立的因果验证模块，从不同角度检验因果关系的可靠性：

1. **DoWhy 适配** — 基于 Pearl 因果图的反事实推理
2. **causal-learn 验证** — 基于约束/评分的因果发现
3. **复合诊断** — 多指标综合评估
4. **反事实桥接** — TRACE 输出到 DoWhy 的转换
5. **可复现仪表板** — 结果稳定性检验
6. **六面板可视化** — 多维度结果展示

## LLaMA 模型规格

| 模型 | 参数量 | 大小 | max_position | 适用场景 | 建议显存 |
|------|--------|------|--------------|----------|----------|
| shehui-llama | 27M | ~108MB | 256 | 大规模文本快速分析 | >= 1.5GB |
| shenji-llama | 469M | ~1.88GB | 1024 | 神学/史诗古文 | >= 3.0GB |
| shehui-llama-v4-archive | 470M | ~1.88GB | 1024 | 旧版归档 | >= 3.0GB |

## 参数预设（presets.yaml）

```yaml
llama:
  threshold: 0.01          # TRACE 因果边显著性阈值
  window_size: 128         # 滑动窗口大小（2-256）
  max_segments: 3          # 最大分段数
  min_valid_tokens: 10     # 最小有效 token 数
  max_edges_for_dowhy: 20  # DoWhy 最大边数
  filter_mode: topn        # 过滤模式
  filter_percentile: 95    # 过滤百分位
  classical_mode: false    # 古典模式（保留虚词）
```

## CLI 用法

```bash
# 环境检查
python run_cli.py env

# 文本分析（默认 llama 预设）
python run_cli.py --text "你的因果分析文本"

# 指定预设
python run_cli.py --text "..." --preset deep

# 完整管线
python run_real_pipeline.py --input input.txt
```

## 依赖

```
torch>=2.0
transformers>=4.30
jieba>=0.42
dowhy>=0.14
pydot<3.0
networkx>=2.8
causal-learn>=0.1
```
