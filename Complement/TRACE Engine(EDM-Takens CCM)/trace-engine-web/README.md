# TRACE Engine Web MVP

基于 `trace-engine` Skill 的 NodeJS 轻量 Web 接口，支持上传文本并通过 Server-Sent Events (SSE) 实时流式调用 Python Skill 进行因果计算。

## 前置条件

- Node.js >= 18
- Python 3.10+（已安装 `trace-engine` Skill 所需依赖：numpy, pandas, dowhy 等）
- 可选：`jieba`（提升中文分词效果，`pip install jieba`）

## 快速启动

### Windows PowerShell（推荐）

```powershell
cd trace-engine-web
.\start.ps1
```

### Windows CMD

`start.bat` 是一个轻量包装器，实际逻辑在 `start.ps1` 中执行，避免旧版
CMD 批处理解析中文/复杂结构时闪退。

```cmd
cd trace-engine-web
start.bat
```

### 停止残留服务

若之前启动的 Node 进程仍在运行，导致端口或文件被锁定：

```powershell
.\stop_servers.ps1
# 或
.\stop_servers.bat
```

### 手动启动

```powershell
cd trace-engine-web
npm install
npm start
```

服务默认监听 `http://localhost:3000`，端口被占用时自动尝试 3001–3020。

## 使用界面

打开浏览器访问 `http://localhost:3000`：

1. 在左侧文本框输入中文段落，或上传 `.txt` / `.md` 文件
2. 选择分析模式：
   - **LIGHT**：快速因果推断（TRACE + DoWhy 核心流程，约 1–3 秒）
   - **DEEP**：完整六战士深度诊断（额外执行 CCM、EDM、HAVOK、causallearn PC/GES，预计 10–60 秒或更长）
3. 点击 `> RUN_ANALYSIS`
4. 右侧终端面板会实时显示分析阶段与日志
5. 进度条同步展示当前阶段（分词 → 构图 → 识别 → 估计 → 反驳 → 反事实扫描 → [DEEP] 六战士诊断 → [DEEP] 稳定性分析 → 报告生成）
6. 分析完成后，左侧下方出现结构化结果面板，包含：
   - 核心指标（概念数、边数、ATE、95% CI、可识别性、反驳数、模式、耗时）
   - 质谱级因果参数网格
   - 执行时间剖面（各阶段毫秒级 breakdown）
   - 数据与模型诊断（token 覆盖率、矩阵密度、BPE 类型、UNK 率、条件数、最大相关性等）
   - 可识别性与估计后端详情
   - **概念词表与频率**（含 CCM 资格标记）
   - **邻接矩阵热力图**（可视化 TRACE 因果强度）
   - **稳定性与鲁棒性分析**（bootstrap 边稳定性、置换 p-value、K-fold CV，DEEP 模式）
   - Top 因果边、反事实扫描、反驳测试
   - 六战士诊断卡片（可展开 raw metrics）
7. 可点击 `> OPEN_REPORT.md` 或 `> OPEN_RESULT.json` 查看详细报告
8. 右上角 **SCALE** 滑块可整体放大/缩小 UI（75%–150%，默认 105%，自动保存到 localStorage），点击 RESET 恢复默认
9. 支持 **拖拽上传** 文本文件，支持 **参数预设**（DEFAULT / SENSITIVE / BROAD / DEEP）
10. 任务历史面板支持 **EXPORT** 导出 JSON 与 **CLEAR** 清空

## 技术架构

```
┌─────────────┐      POST/GET /api/analyze-stream      ┌─────────────┐
│   Browser   │  <──────────────────────────────────>  │  NodeJS     │
│  (index.html)     Server-Sent Events (SSE)           │  (server.js)│
└─────────────┘                                       └──────┬──────┘
                                                             │ spawn
                                                             ▼
                                                    ┌─────────────────┐
                                                    │  py_bridge.py   │
                                                    │  (Python)       │
                                                    └───────┬─────────┘
                                                            │ import
                                                            ▼
                                                    ┌─────────────────┐
                                                    │ trace-engine    │
                                                    │ Skill modules   │
                                                    │ (relative ref)  │
                                                    └─────────────────┘
```

### 后端端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET/POST | `/api/analyze-stream` | SSE 流式分析（POST 用于长文本避免 URL 超限） |
| POST | `/api/analyze-text` | 同步分析纯文本 `{text, mode, config}` |
| POST | `/api/analyze-file` | 同步分析上传文件 `multipart/form-data: file, mode, config` |
| POST | `/api/cancel/:id` | 取消正在运行的任务 |
| GET | `/api/result/:id` | 获取 JSON 结果 |
| GET | `/api/report/:id` | 获取 Markdown 报告 |
| GET | `/api/jobs` | 任务历史与活跃任务 |
| GET | `/api/jobs/export` | 导出任务历史 JSON |
| POST | `/api/jobs/clear` | 清空任务历史 |
| GET | `/api/jobs/:id` | 单任务状态与结果路径 |
| POST | `/api/retry/:id` | 重试失败/超时/已取消任务 |
| GET | `/api/health` | 健康检查（含 Skill 就绪与磁盘可写性） |
| GET | `/api/config` | 当前服务端配置 |
| GET | `/api/queue` | 当前队列与并发状态 |
| GET | `/api/version` | 服务版本与识别信息 |
| GET | `/api/presets` | 参数预设 |
| GET | `/api/schema` | 桥接参数 Schema（用于前端表单与多云校验） |
| GET | `/api/metrics` | 运行时指标（活跃任务、历史状态统计等） |
| POST | `/api/admin/cleanup` | 手动触发输出目录 TTL 清理 |

### 实时事件类型

SSE 流推送以下事件：

- `stage`：阶段更新，包含 `stage` 名称与 `progress`（0.0~1.0）
- `log`：日志消息，包含 `level`（info/stage/error/warn/stderr）与 `message`
- `result`：分析完成后的完整结果
- `error`：错误信息
- `done`：流结束标记

### Python 桥接脚本 (`py_bridge.py`)

`py_bridge.py` 是 NodeJS 与 Skill 之间的独立桥接层：

1. 从 stdin 读取原始文本
2. 使用 `jieba` 分词并加载领域词典（信息茧房、观点极化等）
3. 调用 `_token_filters.is_valid_concept` 过滤虚词、标点、BPE 碎片
4. 提取高频概念，基于滑动窗口共现 + 方向启发式构建概念级因果图
5. 调用 `counterfactual_bridge.TRACE2DoWhy` 完成：
   - 概念聚合与精简图构建
   - 因果效应识别（Identification）
   - ATE 估计（Estimation）
   - 三层反驳测试（Random Common Cause / Placebo Treatment / Data Subset）
   - 反事实扫描（Counterfactual Scan）
6. **DEEP 模式**下额外调用 `six_warriors.assemble_all_six` 执行六战士完整诊断
7. 输出 JSON Lines 日志流、最终 `result.json` 与 `report.md`

输出协议：

```jsonl
{"type": "stage", "stage": "tokenize", "message": "...", "progress": 0.15}
{"type": "log", "level": "info", "message": "..."}
{"type": "result", "payload": {...}}
{"type": "error", "message": "..."}
```

### 为什么 LIGHT 模式很快？

LIGHT 模式只执行 Skill 的**核心因果推断管线**：

- 文本分词 + 概念提取
- 滑动窗口构图
- DoWhy 识别/估计/反驳
- 反事实扫描

它**跳过**了六战士中的 CCM/EDM/HAVOK 深度时序分析以及 causallearn 的 PC/GES 约束/评分搜索。这些搜索在小样本上可能非常慢（数十秒到数分钟），因此 LIGHT 模式“快”是设计行为。如需完整验证，请切换到 **DEEP** 模式。

## 配置 Skill 目录

默认通过相对路径引用工作副本 Skill：

```
../trace-engine/examples/counterfactual_hybrid
```

可通过环境变量指向成品目录（或任意独立部署位置）：

```powershell
$env:TRACE_ENGINE_SKILL_DIR = "G:\git\Annals-of-the-Great-Simplicity-main\Annals-of-the-Great-Simplicity\Complement\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid"
npm start
```

修改 `start.ps1` 或 `start.bat` 中对应的注释行可永久生效。

## 项目结构

```
trace-engine-web/
├── start.ps1              # PowerShell 一键启动脚本（推荐）
├── start.bat              # CMD 包装脚本（调用 start.ps1，避免闪退）
├── stop_servers.ps1       # 结束残留 Node 进程
├── stop_servers.bat       # stop_servers.ps1 的 CMD 包装
├── package.json           # NodeJS 依赖
├── server.js              # Express + SSE 服务端
├── py_bridge.py           # Python 桥接脚本
├── sample_input.txt       # 示例输入文本
├── README.md              # 本文档
├── .gitignore             # 排除运行时产物
├── work/                  # 运行时产物（启动日志、输出目录）
│   ├── sync_product.py    # 同步到成品目录的脚本
│   └── outputs/           # 任务输出（按 UUID 存放）
├── tests/
│   ├── test_api.py        # API 端到端测试脚本
│   └── test_upload.py     # 文件上传兼容性测试
└── public/
    └── index.html         # 极客风格前端页面
```

## 工业性设计要点

- **无状态服务**：每个分析任务独立生成 `work/outputs/<uuid>/`，支持并发
- **进程隔离**：每次分析 spawn 独立 Python 子进程，异常不影响主服务
- **取消机制**：通过 `activeJobs` 表管理子进程，支持 `POST /api/cancel/:id`
- **流式反馈**：SSE 替代轮询，降低延迟，提升长任务体验
- **错误降级**：jieba 缺失时自动回退到正则分词；Skill 依赖缺失时通过 SSE 返回明确错误
- **路径可移植**：无硬编码绝对路径，依赖相对路径或环境变量
- **响应式 UI**：CSS `clamp()` + `--ui-scale` 变量 + SCALE 滑块（默认 105%），适配多种浏览器缩放偏好
- **结果缓存**：相同文本+模式在内存中复用结果，减少重复计算
- **并发控制**：最大并发任务数可配置，超额任务自动入队
- **超时保护**：单次分析默认 5 分钟超时，防止资源耗尽
- **日志持久化**：服务端运行日志写入 `work/server.log`
- **任务历史**：`/api/jobs` 可查看活跃任务与最近 50 条历史
- **队列状态**：`/api/queue` 可查看当前并发与排队任务
- **健康检查**：`/api/health` 检测 Skill 目录与核心文件可用性
- **TTL 清理**：输出目录默认 24 小时自动清理，可通过环境变量调整
- **可配置桥接器**：通过 `TRACE_BRIDGE_CONFIG` 可调整阈值、窗口大小、最大概念数等参数
- **POST 流式接口**：`/api/analyze-stream` 支持 POST，避免长文本 URL 长度限制
- **CORS 支持**：便于多云/跨域部署
- **参数预设**：前端一键切换 DEFAULT / SENSITIVE / BROAD / DEEP 场景
- **任务历史管理**：支持导出 JSON 与清空，记录耗时与完成时间
- **服务版本识别**：`/api/version` 便于负载均衡与多云探针
- **请求追踪 ID**：每个请求附带 `traceId`，错误响应与日志可串联定位
- **参数 Schema**：`/api/schema` 统一描述可配参数范围，便于多云校验与前端表单生成
- **缓存键隔离**：缓存键包含 `mode+config+text`，避免不同参数复用错误结果
- **运行时指标**：`/api/metrics` 提供活跃任务、历史状态统计等监控数据
- **单任务查询与重试**：`/api/jobs/:id` 与 `/api/retry/:id` 提升人工运维体验
- **磁盘可写性探针**：健康检查包含工作目录写入测试

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `3000` | 服务端口号 |
| `TRACE_ENGINE_SKILL_DIR` | `../trace-engine/examples/counterfactual_hybrid` | Skill 目录路径 |
| `TRACE_OUTPUT_TTL_MS` | `86400000` | 输出目录保留时间（毫秒） |
| `TRACE_MAX_CACHE` | `32` | 内存结果缓存最大条目数 |
| `TRACE_MAX_JOB_HISTORY` | `100` | 任务历史最大保留数 |
| `TRACE_MAX_TEXT_LENGTH` | `500000` | 单次分析最大文本长度 |
| `TRACE_PYTHON_CMD` | `python` | Python 可执行文件命令 |
| `TRACE_MAX_CONCURRENT` | `2` | 最大并发分析任务数 |
| `TRACE_JOB_TIMEOUT_MS` | `300000` | 单次分析超时时间（毫秒） |
| `TRACE_BRIDGE_CONFIG` | `''` | 传给 Python 桥接器的 JSON 配置（阈值、窗口、最大概念数等） |
| `TRACE_CORS_ORIGIN` | `*` | CORS 允许来源（多云/跨域部署） |
| `TRACE_WEB_VERSION` | `1.1.0` | 服务版本号（用于多云识别） |

## 注意事项

- `work/` 目录为运行时产物，已被 `.gitignore` 排除
- 文本越长、因果描述越清晰，分析效果越好
- 首次 `npm install` 需要网络访问
- 如需完全独立部署，可将 Skill 目录复制到本项目的 `skill/` 下并修改 `server.js` 中的 `CONFIG.skillDir`
