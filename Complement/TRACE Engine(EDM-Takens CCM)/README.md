# TRACE Engine (EDM-Takens CCM) — 便携成品目录

本目录包含 `trace-engine`（因果推断引擎）与 `trace-engine-web`（Web 服务）两个子项目，已整理为可独立运行的成品结构。

## 目录结构

```
.
├── README.md                 # 本文件
├── verify_portable.py        # 独立运行性审计脚本
├── trace-engine/             # Python 因果推断引擎
│   ├── health_check.py       # 引擎健康检查
│   ├── build_bridge_schema.py # 桥接参数 Schema 生成（含 --presets-only 模式）
│   ├── examples/
│   │   └── counterfactual_hybrid/  # 六战士因果分析核心
│   │       ├── _causallearn_utils.py    # causallearn 工具集
│   │       ├── _config.py               # 配置
│   │       ├── _logging.py              # 日志
│   │       ├── _token_filters.py        # token 过滤
│   │       ├── causallearn_validator.py # causallearn 校验器
│   │       ├── compound_diagnostic.py   # 复合诊断引擎
│   │       ├── counterfactual_bridge.py # TRACE↔DoWhy 桥接
│   │       ├── dowhy_adapter.py         # DoWhy 适配器
│   │       ├── dowhy_auditor.py         # DoWhy 审计
│   │       ├── minimal_dataframe.py     # 最小数据框工具
│   │       ├── pearl_counterfactual.py  # Pearl 反事实
│   │       ├── pipeline_helpers.py      # 流水线辅助
│   │       ├── simulation_model.py      # 仿真模型
│   │       ├── six_warriors.py          # 六战士装配
│   │       └── ...
│   ├── models/               # 训练好的 LLaMA 模型（SUPER 模式使用）
│   ├── tests/test_skill.py   # 引擎自检测试
│   └── date/                 # 训练/测试数据
└── trace-engine-web/         # Node.js Web 服务
    ├── start.ps1             # 启动脚本
    ├── stop_servers.ps1      # 停止 stale 服务
    ├── server.js             # Express 初始化与路由挂载（232 行，模块化拆分）
    ├── py_bridge.py          # Python 桥接（LIGHT / DEEP）
    ├── llama_worker.py       # 常驻 LLaMA Worker（SUPER）
    ├── lib/                  # 状态管理（state.js）+ 工具函数（utils.js）
    ├── middleware/           # 鉴权（auth.js）+ CORS/安全头（index.js）
    ├── routes/               # API 路由（analysis.js, jobs.js, system.js, admin.js）
    ├── services/             # 分析服务（analysis.js）+ LLaMA Worker 管理（llamaWorker.js）
    ├── schema/               # result_schema.json + bridge_schema.json
    ├── public/
    │   ├── css/              # main.css + theme.css
    │   ├── js/               # app.js + sse.js + render.js + schema.js + jobs.js
    │   └── index.html        # 前端页面
    └── tests/
        ├── test_api.py
        └── test_upload.py
```

## 架构概览

- **trace-engine**：六战士因果分析框架，含复合诊断引擎（`compound_diagnostic.py`）。`examples/counterfactual_hybrid/` 下汇集了 TRACE↔DoWhy 桥接（`dowhy_adapter.py`、`counterfactual_bridge.py`）、causallearn 校验（`causallearn_validator.py`、`_causallearn_utils.py`）、Pearl 反事实（`pearl_counterfactual.py`）、最小数据框工具（`minimal_dataframe.py`）、仿真模型（`simulation_model.py`）与流水线辅助（`pipeline_helpers.py`），由 `six_warriors.py` 装配为六合一深度诊断流程。
- **trace-engine-web**：模块化 Express 服务（`server.js` 232 行，仅负责 Express 初始化与路由挂载），具体逻辑分散到 `lib/`（状态/工具）、`middleware/`（鉴权层 `auth.js`、CORS/helmet 安全中间件）、`routes/`（API 路由）、`services/`（分析服务、LLaMA Worker 管理）、`schema/`（result schema 契约）。前端拆分为 `public/css/` 与 `public/js/`（含 SSE 重连 `sse.js`、渲染 `render.js`、Schema 校验 `schema.js`）。

## 安全特性

- **鉴权分级**：`TRACE_API_KEY`（普通用户，保护分析/结果/任务端点）+ `TRACE_ADMIN_KEY`（管理员，保护 `/api/admin/cleanup`、`/api/jobs/clear`），分级保护。未设置时鉴权自动禁用（开发模式兼容）。
- **安全头**：`helmet` 中间件统一注入安全响应头。
- **限流**：`express-rate-limit` 对 `/api/analyze-*` 端点限流（默认 10 次/分钟）。
- **CORS**：默认拒绝通配符，需通过 `TRACE_CORS_ORIGIN` 显式配置白名单。

## 环境要求

- Python 3.11+（推荐 3.13）
- Node.js 18+
- 依赖包：见 `trace-engine/requirements.txt` 与 `trace-engine-web/package.json`

## 快速开始

### 1. 独立运行性审计（推荐首先执行）

```powershell
cd "TRACE Engine(EDM-Takens CCM)"
python verify_portable.py
```

审计将检查：
- 目录结构完整性
- 无运行时产物污染
- 引擎模块导入与健康状态
- 引擎自检测试
- Web 服务健康检查

### 2. 启动 Web 服务

```powershell
cd "TRACE Engine(EDM-Takens CCM)\trace-engine-web"
powershell -ExecutionPolicy Bypass -File start.ps1
```

服务将自动：
- 检测并安装 npm 依赖（首次）
- 探测可用端口（默认 3000-3020）
- 选择可写工作目录（优先脚本目录，只读时回退到 `%TEMP%\trace-engine-web-work`）

浏览器访问：http://localhost:3000

### 3. SUPER 模式（LLaMA 模型驱动）

Web 界面提供三种分析模式：

- **LIGHT**：jieba 概念图 + 简化流程（1–3 秒）
- **DEEP**：jieba 概念图 + 完整六战士深度诊断（10–60 秒）
- **SUPER**：调用 `trace-engine/models/` 下可选的三个 LLaMA 模型之一执行真正的 token-level TRACE 因果发现，再走完整六合一诊断（首次需加载模型，分析耗时视文本长度与模型规模而定）

> SUPER 模式由常驻 LLaMA Worker 处理，单线程顺序执行。模型文件较大，首次同步时自动复制到 `trace-engine/models/`。
>
> 可选模型规格（三选一）：
> - **shehui-llama**（默认，27M 参数 / ~108MB / max_position=256）：轻量高效，~800 pps，适合大规模文本快速刨析，建议显存 ≥1.5GB
> - **shenji-llama**（469M 参数 / ~1.88GB / max_position=1024）：神学/史诗古文，~10-40 pps @ RTX 3050，建议显存 ≥3.0GB
> - **shehui-llama-v4-archive**（470M 参数 / ~1.88GB / max_position=1024）：旧版归档，因果发现能力较弱，建议显存 ≥3.0GB
>
> Web 端会自动尝试 FP16 加载并在显存不足时给出提示。
>
> 参数预设：Web 界面提供 **LLAMA** 预设（`threshold=0.01, window_size=128, max_segments=3`），专为过拟合 TRACE LLaMA 模型设计。分析 Shenji 古文时可开启 `classical_mode=true`，保留 之/乎/者/也 等虚词。

### 4. 停止服务

```powershell
cd "TRACE Engine(EDM-Takens CCM)\trace-engine-web"
powershell -ExecutionPolicy Bypass -File stop_servers.ps1
```

### 5. 仅运行引擎（命令行）

```powershell
cd "TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid"
python run_cli.py --text "你的因果分析文本"
```

## 环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `TRACE_WORK_DIR` | 工作/输出目录 | `C:\trace-work` |
| `TRACE_ENGINE_SKILL_DIR` | 引擎 Skill 路径 | `...\trace-engine\examples\counterfactual_hybrid` |
| `TRACE_PYTHON_CMD` | Python 命令 | `python` 或 `python3` |
| `PORT` | Web 服务端口 | `3000` |
| `TRACE_STAGE_TIMEOUT_MS` | SUPER 模式阶段性进度看门狗超时（毫秒），无 stage 更新则判定 hang | `900000` |
| `TRACE_API_KEY` | 普通用户鉴权密钥，保护分析/结果/任务等端点；未设置时鉴权自动禁用 | `your-strong-api-key` |
| `TRACE_ADMIN_KEY` | 管理员密钥，保护 `/api/admin/cleanup`、`/api/jobs/clear`；需与 `TRACE_API_KEY` 配合使用 | `your-strong-admin-key` |
| `TRACE_CORS_ORIGIN` | CORS 允许来源，默认拒绝通配符，需显式配置白名单 | `http://localhost:5173` |

## 维护说明

- 运行时产物（`outputs/`、`__pycache__/`、`*.log`）已被 `.gitignore` 排除
- 同步源目录到本成品目录请使用源端的 `sync_product.py`
- 遇到目录锁定时，运行 `trace-engine-web/stop_servers.ps1` 清理 stale 进程后再同步
- **桥接 Schema 生成**：`trace-engine/build_bridge_schema.py --presets-only` 仅供 Web 端 `loadPresets()` 调用，生成预设白名单（不重建全量 schema）。完整重建使用不带参数的 `build_bridge_schema.py`。

## 支持与故障排查

- 服务启动失败：检查 `work/server.log` 与 `work/start.log`
- Python 依赖缺失：运行 `pip install -r trace-engine/requirements.txt`
- 端口冲突：脚本会自动尝试 3000-3020，或手动设置 `PORT` 环境变量
- SUPER 模式加载模型慢/OOM：关闭其它占用显存的程序，或在环境变量中设置 `TRACE_MODEL_DTYPE=fp32` 强制 FP32；必要时缩短文本或减小 `window_size`/`max_segments`
- Shehui-LLaMA 因果边稀少：使用 `llama` 预设（`threshold=0.01`）可检出非零因果边；若仍偏少可尝试切换到 Shenji-LLaMA 或改用 DEEP 模式
