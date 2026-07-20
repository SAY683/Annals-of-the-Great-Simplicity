# trace-to-edm: 三层元因果控制论桥接系统

```
  ┌──────────────────────────────────────────────────────────┐
  │        Meta-Causal Cybernetics Bridge                    │
  │        元因果控制论 · 三层桥接器                          │
  └──────────────────────────────────────────────────────────┘
```

## 架构

```
                              ┌─ Layer 1: 元SCM参数 (23列)
  TRACE引擎 ──→ result.json ──┤
           ──→ Qwen编码 ──────├─ Layer 2: 世俗PCA投影 (4列)
                              └─ Layer 3: 八正道审计 (24列)
                                       ↓
                              narrative_meta_trajectories.csv (54列)
                                       ↓
                              EDM-Takens 动力学预测 → 相变预警
```

## 项目结构

```
trace-to-edm/
├── server.js              # Node.js Web 服务 (Express + SSE, 端口3100)
├── bridge.py              # Python CLI 入口 (三层管线 + 项目管理)
├── start.bat              # 一键启动脚本
│
├── config.py              # 全局配置 (路径/列定义/参数)
├── project_manager.py     # 项目CRUD (每个项目自包含)
├── dataset_manager.py     # 数据集注册表 (dataset.json)
├── work_scanner.py        # TRACE工作目录扫描 + 清理
├── csv_builder.py         # 轨迹CSV构建器 (54列对齐)
├── edm_trigger.py         # EDM-Takens API 触发器
│
├── layer1_meta_scm.py     # L1: 元SCM参数提取 (23列)
├── layer2_semantic.py     # L2: 世俗PCA投影 (4列)
├── layer3_sacred.py       # L3: 八正道零样本探针 (24列)
│
├── public/                # Web 前端 (双栏仪表盘)
│   ├── index.html
│   ├── css/main.css
│   └── js/app.js
│
├── projects/              # 项目数据 (每个项目自包含)
│   ├── _index.json        #   项目注册表
│   └── {name}/             #   单个项目
│       ├── project.json
│       ├── dataset.json
│       ├── narrative_meta_trajectories.csv
│       ├── inputs/        #   项目专属输入
│       ├── outputs/       #   项目专属输出
│       └── cache/         #   PCA + 神圣向量缓存
│
├── sacred_texts/          # 八正道定义文本 (8本经书)
├── data/                  # 全局模板 (示例CSV)
│   └── inputs/
├── archive/               # 历史归档
└── README.md
```

## 快速开始

```bash
cd .skills/trace-to-edm
start.bat
```

浏览器打开 `http://localhost:3100`

### 工作流

```
1. 扫描 TRACE 工作目录 → 勾选 UUID → "+ 加入数据集"
2. (可选) 粘贴文本或选 CSV → "+ 将文本加入数据集"
3. 数据集面板 → "▶ 运行管线" → 实时SSE进度
4. 轨迹积累 ≥15 行 → EDM 触发 → 选择预测目标 → 动力学分析
```

## API 端点表（共 25 端点）

> 元审计 Q5 同步 (2026-07-20)：之前任务卡曾误列 13 端点，实际盘点为 25 端点（含数据集 / 项目 / 工作目录 / 模型管理）。下表与 `server.js` 中的 `app.<method>(...)` 路由 1:1 对应，行号与 `MICROSERVICE_API_DESIGN.md` 附录 A.3 一致。

| # | 方法 | 端点 | 说明 | server.js 行号 |
|---|------|------|------|----------------|
| 1 | GET | `/api/status` | 轨迹状态 + EDM 就绪度 | 147 |
| 2 | GET | `/api/trajectory` | 当前轨迹 CSV (JSON) | 200 |
| 3 | POST | `/api/trajectory/clear` | 清空当前项目轨迹 | 205 |
| 4 | POST | `/api/run` | 提交文本管线任务 (Mode A, SSE) | 226 |
| 5 | POST | `/api/replay` | 提交回填任务 (Mode B, SSE) | 316 |
| 6 | POST | `/api/edm/trigger` | 触发 EDM 分析 | 402 |
| 7 | GET | `/api/jobs` | 任务历史 (active + 50 条) | 456 |
| 8 | GET | `/api/dataset` | 当前项目数据集 entries + summary | 491 |
| 9 | POST | `/api/dataset/add` | 批量加入 replay UUID 条目 | 500 |
| 10 | POST | `/api/dataset/add-text` | 批量加入文本条目（含 EDM 反馈环） | 510 |
| 11 | POST | `/api/dataset/remove` | 删除单条条目 | 529 |
| 12 | POST | `/api/dataset/clear-processed` | 清理已处理标记 | 534 |
| 13 | POST | `/api/dataset/reset` | 重置全部为 pending | 539 |
| 14 | POST | `/api/dataset/update-ts` | 更新条目 timestamp | 544 |
| 15 | POST | `/api/pipeline/run` | 统一管线（聚合回填+文本, SSE） | 665 |
| 16 | GET | `/api/models` | 列出可选 Qwen 模型 | 739 |
| 17 | POST | `/api/models/activate` | 激活 Qwen 模型（白名单校验） | 747 |
| 18 | GET | `/api/projects` | 列出项目 | 774 |
| 19 | POST | `/api/projects` | 创建项目 | 783 |
| 20 | PUT | `/api/projects/activate` | 切换激活项目 | 794 |
| 21 | DELETE | `/api/projects/:name` | 删除项目 | 805 |
| 22 | GET | `/api/work-scan` | 扫描 TRACE 工作目录 | 816 |
| 23 | DELETE | `/api/work-uuid/:uuid` | 删除指定 UUID 工作目录 | 825 |
| 24 | POST | `/api/work-clean` | 清理孤儿/无效工作目录 | 843 |
| 25 | POST | `/api/replay-uuids` | 选定 UUID 回填到当前项目 (SSE) | 864 |

> 注：根 `/`（express.static 托管前端面板）不计入 25 个 API 端点之列。`POST /api/replay-all` 在文档中常被提及，但代码实现上由 `/api/replay` 以 `replay_all=true` 复用，并非独立路由，故不单列。

## CLI 命令

```bash
# 项目管理
python bridge.py --list-projects           # 列出项目
python bridge.py --project "项目名"         # 切换项目
python bridge.py --create-project "新项目"  # 创建项目
python bridge.py --delete-project "旧项目"  # 删除项目

# 工作目录
python bridge.py --scan-work               # 扫描 TRACE 工作目录
python bridge.py --clean-work --dry-run    # 预览清理

# 管线 (直接模式, 不走Web)
python bridge.py --replay-all              # 一键回填全部历史
python bridge.py --input xxx.csv           # 文本管线批处理
python bridge.py --text "..." --ts "..."   # 单条文本

# EDM
python bridge.py --edm-only --target ate   # 触发EDM分析
python bridge.py --status                  # 轨迹状态
```

## EDM 预测目标 (20列)

| 层 | 列 | 说明 |
|----|-----|------|
| L1 | `ate`, `adj_density`, `max_delta_nll`, `ci_width`, `edge_count`, `ccm_coverage_pct` | 因果系统诊断 |
| L2 | `z_pca_1`, `z_pca_2`, `z_pca_3`, `secular_entropy` | 世俗话语流形 |
| L3 | `z_福音`~`z_觉爱` (8轴) + `dz_存在`, `dz_觉爱` (2差分) | 八正道审计 |

## 数据列全表 (54列)

| 分组 | 列数 | 内容 |
|------|------|------|
| Meta | 3 | `time_step`, `text_hash`, `source_label` |
| L1 因果 | 6 | `ate`, `ate_ci_lower/upper`, `ci_width`, `refuted_count`, `identifiable` |
| L1 图结构 | 4 | `concept_count`, `edge_count`, `adj_density`, `max_delta_nll` |
| L1 诊断 | 6 | `concept_coverage`, `condition_number`, `unk_rate`, `ccm_coverage_pct`, `ccm_verdict`, `edm_rho_high/mid` |
| L1 其他 | 5 | `havok_status`, `havok_linear_pct`, `causallearn_consensus`, `edge_stability_mean`, `permutation_p_value`, `total_ms` |
| L2 | 4 | `z_pca_1`, `z_pca_2`, `z_pca_3`, `secular_entropy` |
| L3 投影 | 8 | `z_福音`, `z_吉祥`, `z_奥美`, `z_存在`, `z_自孕`, `z_弥赛亚`, `z_Alice`, `z_觉爱` |
| L3 差分 | 16 | `dz_*` (8), `d2z_*` (8) |

## 技术依赖

- Python 3.10+ (numpy, pandas, sklearn, torch, transformers)
- Node.js 18+ (express)
- TRACE 引擎 (`.skills/trace-engine-web/`)
- **EDM-Takens Web** (`.skills/edm-takens-web/`) — EDM 触发和反馈环需要此后端运行在 `localhost:8000`
- Qwen2.5-1.5B (本地模型)

## EDM 反馈环

点击「触发 EDM 分析」后:
1. 提交 EDM 任务到 `edm-takens-web` API
2. 每 3 秒轮询任务状态
3. 完成后检测结果中的非线性信号
4. 如发现相变 → 提示用户将异常时间点文本加入数据集 (DEEP 模式再分析)

**前置条件**: `edm-takens-web` 后端必须运行 (`cd .skills/edm-takens-web && python run_backend.py`)

## EDM 时间范围

在 EDM 触发面板中设置「时间范围」起始/结束 (如 `2026-07-01` ~ `2026-07-17`),
CSV 会在发送到 EDM 前按 `time_step` 列过滤。留空则使用全部数据。

## 趋势图

轨迹表格上方有 Canvas 折线图, 实时显示三条曲线:
- **ATE** (绿) — 因果效应强度变化
- **z_存在** (蓝) — 本体论距离漂移
- **secular_entropy** (紫) — 话语多样性演化

管线完成后自动刷新图表。

## Layer 2 背景 PCA

样本不足 10 条时使用基于 8 个神圣向量的背景 PCA (非随机),
确保第一条文本就有有意义的 `z_pca_1` 值。
积累 ≥10 条后自动切换到项目专属 PCA。
