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

## API 端点表（共 33 端点）

> 元审计 Q8+ 同步 (2026-07-20)：新增 `GET /api/edm/poll/:id` 代理端点（P2修复：避免浏览器 CORS 阻拦 trace-to-edm:3100 → edm-takens-web:8000 的跨域请求）。
> 元审计 Q12+ 同步 (2026-07-25)：补齐 `/api/health`、`/api/version`、`/api/orthogonality`、`/api/trajectory/export/md`、`/api/trajectory/report`、`/api/inputs`、`/api/work-uuid/:uuid/text` 共 7 个遗漏端点。

| # | 方法 | 端点 | 说明 | server.js 行号 |
|---|------|------|------|----------------|
| 1 | GET | `/api/health` | 健康检查（服务名 + 时间戳） | 1035 |
| 2 | GET | `/api/version` | 版本号（从 package.json 读取） | 1041 |
| 3 | GET | `/api/status` | 轨迹状态 + EDM 就绪度 | 1053 |
| 4 | GET | `/api/orthogonality` | 八正道正交性报告（Frobenius 距离等元审计） | 1106 |
| 5 | GET | `/api/trajectory` | 当前轨迹 CSV (JSON) | 1128 |
| 6 | POST | `/api/trajectory/clear` | 清空当前项目轨迹 | 1133 |
| 7 | GET | `/api/trajectory/export/md` | 一键导出人话版 Markdown 报告 | 1154 |
| 8 | GET | `/api/trajectory/report` | 查看最新人话版报告（支持 ?format=html） | 1173 |
| 9 | POST | `/api/run` | 提交文本管线任务 (Mode A, SSE) | 1192 |
| 10 | POST | `/api/replay` | 提交回填任务 (Mode B, SSE) | 1285 |
| 11 | POST | `/api/edm/trigger` | 触发 EDM 分析 | 1374 |
| 12 | GET | `/api/edm/poll/:jobId` | EDM 轮询代理（避免 CORS） | 1460 |
| 13 | GET | `/api/jobs` | 任务历史 (active + 50 条) | 1495 |
| 14 | GET | `/api/inputs` | 列出全局/项目输入 CSV 文件 | 1531 |
| 15 | GET | `/api/dataset` | 当前项目数据集 entries + summary | 1553 |
| 16 | POST | `/api/dataset/add` | 批量加入 replay UUID 条目 | 1562 |
| 17 | POST | `/api/dataset/add-text` | 批量加入文本条目（含 EDM 反馈环） | 1572 |
| 18 | POST | `/api/dataset/remove` | 删除单条条目 | 1592 |
| 19 | POST | `/api/dataset/clear-processed` | 清理已处理标记 | 1597 |
| 20 | POST | `/api/dataset/reset` | 重置全部为 pending | 1602 |
| 21 | POST | `/api/dataset/update-ts` | 更新条目 timestamp | 1607 |
| 22 | POST | `/api/pipeline/run` | 统一管线（聚合回填+文本, SSE） | 1754 |
| 23 | GET | `/api/models` | 列出可选 Qwen 模型 | 1845 |
| 24 | POST | `/api/models/activate` | 激活 Qwen 模型（白名单校验） | 1859 |
| 25 | GET | `/api/projects` | 列出项目 | 1898 |
| 26 | POST | `/api/projects` | 创建项目 | 1919 |
| 27 | PUT | `/api/projects/activate` | 切换激活项目 | 1933 |
| 28 | DELETE | `/api/projects/:name` | 删除项目 | 1948 |
| 29 | GET | `/api/work-scan` | 扫描 TRACE 工作目录 | 1964 |
| 30 | DELETE | `/api/work-uuid/:uuid` | 删除指定 UUID 工作目录 | 1973 |
| 31 | POST | `/api/work-clean` | 清理孤儿/无效工作目录 | 1996 |
| 32 | POST | `/api/replay-uuids` | 选定 UUID 回填到当前项目 (SSE) | 2024 |
| 33 | GET | `/api/work-uuid/:uuid/text` | 读取指定 UUID 工作目录的输入文本 | 2098 |

> 注：根 `/`（express.static 托管前端面板）不计入 33 个 API 端点之列。`POST /api/replay-all` 由 `/api/replay` 以 `replay_all=true` 复用。

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
1. 提交 EDM 任务到 `edm-takens-web` API（通过 trace-to-edm 后端 Python 子进程）
2. 浏览器通过 `/api/edm/poll/:id` 代理轮询（P2 修复：避免 localhost:3100→8000 CORS 阻拦）
3. 每 3 秒轮询任务状态
4. 完成后检测结果中的非线性信号

### 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| `Failed to fetch` | CORS：浏览器从 :3100 直接请求 :8000 | 改为通过 `/api/edm/poll/` 代理（需重启 trace-to-edm） |
| `edm-takens-web unreachable` | edm-takens-web 后端未启动 | `python run_backend.py` (端口 8000) |
| 隧道连接 1033 | `--protocol http2` 强制 HTTP/2 到本地 dev server | 改用 `--edge-ip-version 4 --no-chunked-encoding`（需 cloudflared ≥2026.7） |
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

## 示例 CSV 文件 (DOC-06)

`data/inputs/news_40_csv_input.csv` 是预置的 40 条新闻文本示例，用于演示 Mode A 文本管线批处理流程。

**CSV 结构（3 列）**:

| 列名 | 类型 | 说明 |
|------|------|------|
| `timestamp` | 字符串 (YYYY-MM-DD) | 事件时间戳，对应轨迹 CSV 的 `time_step` 列；缺失时会用当前时间回填 |
| `text` | 字符串 | 待分析的文本内容（新闻正文/帖子/评论等），将送入 TRACE 引擎进行因果推断 |
| `source` | 字符串 | 来源标签（如 `临海日报`、`财经快讯`），对应轨迹 CSV 的 `source_label` 列 |

**预期用途**:
- 通过 Web 面板「粘贴文本或选 CSV」入口选择该文件 → 「+ 将文本加入数据集」批量导入
- 作为 `POST /api/run` 的 `csv_path` 参数（路径须位于 `data/inputs/` 或 `projects/<name>/inputs/` 下）
- CLI 批处理：`python bridge.py --input data/inputs/news_40_csv_input.csv --mode light`
- 便携式移植验证：验证 `_is_valid_concept_web` 在真实新闻语料上的分词质量

> 文件首行为表头 `timestamp,text,source`，后续 40 行为数据。文本含逗号时无需引号转义（解析器按列数切分）。

## 关于 replay 行字段为空的说明 (DOC-07)

在轨迹 CSV 中，通过 **Mode B (回填)** 产生的行，其 `trace_status`、`trace_mode`、`trace_error`、`ate`、`adj_density` 等 L1 因果字段**为空属于正常现象**，并非数据缺失或算法错误。

**原因**：
- Mode B 回填直接复用历史 TRACE 任务（`trace-engine-web/work/outputs/<uuid>/result.json`）的 L1 结果，**不重新运行 TRACE 因果推断**
- 因此 replay 行只携带历史结果中已有的字段；若历史任务为 `light` 模式（未运行反驳/CCM），则 `refuted_count`、`ccm_coverage_pct` 等字段同样为 0 或空
- `trace_status` 字段在 replay 行为空，表示"该行来自回填，未独立运行 TRACE"

**如何区分**：
- `source_label` 为空 + `text_hash` 为 UUID 前缀 → replay 行（Mode B）
- `source_label` 非空 + `text_hash` 为文本哈希 → 文本行（Mode A）

**建议**：若需要完整的 L1 因果字段，请通过 Mode A 重新对同一文本运行管线（`/api/run` 或 `/api/pipeline/run`），而非使用 Mode B 回填。
