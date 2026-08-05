# 五大项目微服务 API 路由方案 + 前端鲁棒性 + 网页关闭重连机制

> 范围：`f:\攻略\研发测试\.skills` 下五个项目（edm-takens、edm-takens-web、trace-engine、trace-engine-web、trace-to-edm）。
> 目标：在 **不破坏现有 33 + 26 + 29 端点** 的前提下，沉淀一份微服务 API 路由契约、前端鲁棒性方案与网页关闭重连机制，作为后续渐进式微服务化的蓝图。
> 备注：原始任务卡列 trace-to-edm 为 13 端点，Q5 盘点为 25 端点，Q8+ 新增 `/api/edm/poll/:id` 代理端点（CORS 修复），Round 12 续新增 `/api/version`（版本查询），R13+ 新增 `/api/replay-uuids`、`/api/work-uuid/:uuid/text`、`/api/pipeline/run` 等端点，ROUND26 同步后为 33 端点。edm-takens-web 经 routes/* 细化为 29 端点。trace-engine-web 经 routes/* 拆分为 26 端点（system=8 / jobs=8 / analysis=8 / admin=1 + 1 静态 `GET /`，ROUND26 校正）。

---

## 1. 微服务架构总览

### 1.1 五项目的服务定位

| 项目 | 角色 | 语言/运行时 | 端口 | 提供的微服务 | 现有端点数 |
|------|------|------------|------|-------------|-----------|
| **edm-takens** | 算法内核（无独立 API） | Python 3.13 | — | EDM-Takens 流水线（CCM、EmbedDimension、Havok、SovereignHavok、SurrogateTest、AdaptivePipeline）。作为 Python 模块被 `edm-takens-web` 直接 `import` 调用。 | 0 |
| **edm-takens-web** | EDM 分析 Web 服务 | FastAPI / Uvicorn | 8000 | 数据集管理、EDM 分析任务编排、历史归档、结果导出。 | 29 |
| **trace-engine** | 算法内核（无独立 API） | Python 3.13 | — | TRACE 引擎（六战士 + 反事实桥 + DoWhy 适配 + Pearl 反事实）。作为子进程被 `trace-engine-web` 通过 `py_bridge.py` 调用。 | 0 |
| **trace-engine-web** | 文本因果分析 Web 服务 | Express + SSE | 3000 | 文本分析（LIGHT/DEEP/SUPER）、SSE 流式、结果缓存、LLaMA Worker 调度、任务历史。 | 26 |
| **trace-to-edm** | 桥接编排服务 | Express + SSE | 3100 | 三层桥接（L1 元SCM / L2 世俗语义 PCA / L3 八正道）、文本管线 Mode A、回填管线 Mode B、EDM 触发与轮询代理、项目与数据集管理、版本查询。 | 33 |

### 1.2 服务间通信拓扑

```
┌───────────────┐   HTTP/SSE     ┌──────────────────┐   subprocess     ┌─────────────┐
│   Browser     │ ◄──────────►   │  trace-to-edm    │ ◄─────────────►  │ bridge.py   │
│  (5 panels)   │                │  (Express 3100)  │                  │ (Python)    │
└───────┬───────┘                └────────┬─────────┘                  └──────┬──────┘
        │                                 │                                   │
        │ HTTP/SSE                        │ HTTP /api/analyze/jobs             │ spawn
        ▼                                 ▼                                   ▼
┌──────────────────┐   HTTP/SSE   ┌──────────────────┐   subprocess      ┌─────────────┐
│ trace-engine-web │ ◄─────────►  │ edm-takens-web   │ ◄──────────────►  │ edm-takens  │
│  (Express 3000)  │              │ (FastAPI 8000)   │   import / py     │ (Python)    │
└────────┬─────────┘              └──────────────────┘                   └─────────────┘
         │
         │ spawn + JSON Lines (stdin → stdout)
         ▼
┌──────────────────┐
│   trace-engine   │
│  py_bridge.py    │
└──────────────────┘
```

**三种通信模式：**

1. **HTTP/REST**：浏览器 → 任一 Web 服务；trace-to-edm → edm-takens-web（`/api/analyze/jobs`）。
2. **SSE（Server-Sent Events）**：所有长任务流式日志。trace-engine-web 在响应头加 `retry: 5000`；edm-takens-web 用 NDJSON（`application/x-ndjson`）；trace-to-edm 用标准 SSE（`event:` + `data:`）。
3. **subprocess + JSON Lines**：Web 服务调用 Python 内核。
   - `trace-engine-web` → `py_bridge.py`：文本经 `stdin` 写入，事件经 `stdout` 按行 JSON 输出。
   - `trace-to-edm` → `bridge.py`：通过命令行参数 + `--verbose` 标志，stdout 既输出日志也输出 JSON 结果块。
   - `edm-takens-web` → `edm-takens`：直接 `import`（同进程，无子进程开销），通过 `job_store.spawn(job)` 在后台线程跑 `pipeline.run()`。

### 1.3 数据流分类

| 类型 | 定义 | 代表端点 | 端点数 |
|------|------|---------|--------|
| **储存型（Storage）** | 作用于文件系统或 SQLite 持久化，写入后可被后续请求读回 | `POST /api/upload`、`POST /api/history/{id}/archive`、`POST /api/dataset/add`、`POST /api/projects` | 22 |
| **转发型（Forward）** | 不持久化，只把请求转给子进程/上游服务并把输出原样回流 | `POST /api/analyze-stream`、`POST /api/run`、`POST /api/replay`、`POST /api/edm/trigger` | 9 |
| **计算型（Compute）** | 在进程内执行算法（EDM/PCA/CCM），结果可缓存可持久化 | `POST /api/analyze/jobs`、`GET /api/datasets/{filename}/embed_curve`、`GET /api/datasets/{filename}/quality`、`POST /api/pipeline/run` | 11 |
| **只读型（Read-Only）** | 纯查询，无副作用 | `GET /api/health`、`GET /api/datasets`、`GET /api/history`、`GET /api/jobs`、`GET /api/schema` | 28 |
| **治理型（Governance）** | 清理、归档、批量操作、模型切换 | `POST /api/admin/cleanup`、`POST /api/history/cleanup`、`POST /api/jobs/clear`、`POST /api/models/activate` | 10 |

> 总计 88 端点（edm-takens-web 29 + trace-engine-web 26 + trace-to-edm 33，ROUND26 同步对账后校正）。

### 1.4 服务绑定地址规范（Round 19 新增）

**强制规范**: 所有 Web 服务 (trace-engine-web / trace-to-edm / edm-takens-web) 必须绑定 `TRACE_HOST || '127.0.0.1'`, 而非隐式 `0.0.0.0`。

**原因**:
1. **本地开发安全**: 避免服务直接暴露到 LAN/Internet, 防止未授权访问
2. **避免端口冲突**: 0.0.0.0 监听会与系统其他服务端口冲突 (Windows 上尤其明显)
3. **隧道模式兼容**: 外部访问通过 Cloudflare Tunnel 暴露, 不需要服务直接监听 0.0.0.0
4. **IPv6/IPv4 一致性**: `127.0.0.1` 明确走 IPv4, 避免 `localhost` 在某些系统下解析到 `::1` (IPv6) 导致连接失败

**实现位置**:
- `trace-engine-web/server.js`: `app.listen(PORT, process.env.TRACE_HOST || '127.0.0.1', ...)`
- `trace-to-edm/server.js`: `app.listen(PORT, process.env.TRACE_HOST || '127.0.0.1', ...)`
- `edm-takens-web/backend/api.py`: `uvicorn.run(app, host=os.getenv('TRACE_HOST', '127.0.0.1'), ...)`
- `edm-takens-web/frontend/vite.config.js`: proxy target 使用 `http://127.0.0.1:8000` (非 `localhost`)

**生产部署**: 通过环境变量 `TRACE_HOST=0.0.0.0` 在容器/反向代理后放开绑定, 配合防火墙规则限制来源 IP。

---

## 2. API 路由层级体系

将现有 88 个端点按职能归入 5 个逻辑层。**层级不是物理部署**，同一服务可跨多层（如 edm-takens-web 同时提供 L1/L2/L3/L4/L5 端点）。这是后续抽出独立微服务的拆分依据。

### 2.1 L1 — 基础设施层（Health / Config / Schema）

| 端点 | 服务 | 方法 | 数据流 | 请求契约 | 响应契约 |
|------|------|------|--------|---------|---------|
| `/api/health` | edm-takens-web | GET | 只读 | — | `{status, time}` |
| `/api/health` | trace-engine-web | GET | 只读 | — | `{success, status, skillReady, pythonReady, disk, activeJobs, queuedJobs, cacheSize, jobHistory, timestamp}` |
| `/api/config` | trace-engine-web | GET | 只读 | — | `{success, config, bridgeParamSchema, superBridgeParamSchema, modes, presets, llamaModels, llamaWorker, buildInfo}` |
| `/api/version` | trace-engine-web | GET | 只读 | — | `{success, ...BUILD_INFO, skillReady, pythonCmd}` |
| `/api/schema` | trace-engine-web | GET | 只读 | — | `{success, schema, superSchema, resultSchema, modes, presets}` |
| `/api/presets` | trace-engine-web | GET | 只读 | — | `{success, presets}` |
| `/api/status` | trace-to-edm | GET | 只读 | — | `{success, trajectory:{path,rows,columns,edm_ready,edm_targets}, jobs:{active,active_ids}, layers:{l1,l2,l3}}` |
| `/api/health` | trace-to-edm | GET | 只读 | — | `{status, service, time}` |
| `/api/version` | trace-to-edm | GET | 只读 | — | `{success, service, version, node, time}` (Round 12 续新增，版本号从 package.json 读取) |

**错误契约**：L1 端点不应返回 5xx（除非进程崩溃）；`status` 字段使用 `healthy | degraded | down` 三态。

### 2.2 L2 — 数据层（Dataset CRUD / Upload / Inspect）

| 端点 | 服务 | 方法 | 数据流 | 请求契约 | 响应契约 |
|------|------|------|--------|---------|---------|
| `/api/datasets` | edm-takens-web | GET | 只读 | — | `{datasets: string[]}` |
| `/api/upload` | edm-takens-web | POST | 储存 | `multipart/form-data`，`file: UploadFile`（仅 .csv，≤50MB） | `{filename, saved: true, size}`；413 / 415 / 500 |
| `/api/datasets/{filename}/columns` | edm-takens-web | GET | 计算 | path: filename | `{columns, numeric_columns, rows, preview[5], recommended_target}` |
| `/api/datasets/{filename}/recommend` | edm-takens-web | GET | 计算 | query: target_col?, variables? | `{level, params:{q,max_e,auto_fix}, notes[]}` |
| `/api/datasets/{filename}/quality` | edm-takens-web | GET | 计算 | query: target_col?, variables? | `{filename, target_col, columns: {col: {usable_for_edm, warnings, ...}}}` |
| `/api/datasets/{filename}/embed_curve` | edm-takens-web | GET | 计算 | query: target_col, max_e=8 | `{filename, target_col, max_e, E_values[], rho_values[], optimal_E, curve[]}` |
| `/api/dataset` | trace-to-edm | GET | 只读 | — | `{entries[], summary}` |
| `/api/dataset/add` | trace-to-edm | POST | 储存 | `{uuids: string[]}` | `{success, added}` |
| `/api/dataset/add-text` | trace-to-edm | POST | 储存 | `{csv_path?, texts[]}` | `{success, added}` |
| `/api/dataset/remove` | trace-to-edm | POST | 储存 | `{id}` | `{success: true}` |
| `/api/dataset/clear-processed` | trace-to-edm | POST | 储存 | — | `{success: true}` |
| `/api/dataset/reset` | trace-to-edm | POST | 储存 | — | `{success: true}` |
| `/api/dataset/update-ts` | trace-to-edm | POST | 储存 | `{id, timestamp}` | `{success}` |
| `/api/trajectory` | trace-to-edm | GET | 只读 | — | `{columns, rows, total, path?}` |
| `/api/trajectory/clear` | trace-to-edm | POST | 储存 | — | `{success: true, rows: 0}` |
| `/api/projects` | trace-to-edm | GET | 只读 | — | `{projects[], active}` |
| `/api/projects` | trace-to-edm | POST | 储存 | `{name, description?}` | `{success, project}` |
| `/api/projects/activate` | trace-to-edm | PUT | 储存 | `{name}` | `{success, active}` |
| `/api/projects/:name` | trace-to-edm | DELETE | 储存 | path: name | `{success}` |
| `/api/work-scan` | trace-to-edm | GET | 只读 | — | `{uuids[], orphans[], invalid[]}` |
| `/api/work-uuid/:uuid` | trace-to-edm | DELETE | 储存 | path: uuid | `{success, deleted}` |
| `/api/work-clean` | trace-to-edm | POST | 储存 | `{dry_run?, orphans_only?}` | `{success, removed[]}` |
| `/api/models` | trace-to-edm | GET | 只读 | — | `{models[], active}` |
| `/api/models/activate` | trace-to-edm | POST | 治理 | `{model}` (白名单: `qwen2.5-1.5b` / `qwen2.5-3b`) | `{success, active}` |

**错误契约**：4xx 用于参数错误（400）/未找到（404）/冲突（409）；5xx 仅用于内部 Python 调用失败。

### 2.3 L3 — 计算层（Analysis / SSE Stream）

| 端点 | 服务 | 方法 | 数据流 | 请求契约 | 响应契约 |
|------|------|------|--------|---------|---------|
| `/api/analyze/jobs` | edm-takens-web | POST | 计算+储存 | `multipart/form-data`：`filename, target_col?, variables?, auto_fix, intensity, project_name?, q?, max_e?` | `{job_id, status, profile, data_quality_warning?}` |
| `/api/analyze/jobs/{job_id}` | edm-takens-web | GET | 只读 | path: job_id, query: limit_logs=200 | `{id, status, logs[], result?, error?, ...}`；404 |
| `/api/analyze/jobs/{job_id}/stream` | edm-takens-web | GET | 转发 | path: job_id | `application/x-ndjson` 流：每行 `{type: log\|result\|error, data}` |
| `/api/analyze` | edm-takens-web | POST | 计算 | 同 /jobs 但阻塞 | `{...result, logs}`；429（槽位满）/500 |
| `/api/analyze/stream` | edm-takens-web | GET | 转发 | query: filename, target_col?, ... | NDJSON 流 |
| `/api/results/{image_path}` | edm-takens-web | GET | 只读 | path: image_path | `image/*`；400（路径越界）/404 |
| `/api/analyze-stream` | trace-engine-web | GET/POST | 转发 | `{text, mode: light\|deep\|super, config?, id?}` | `text/event-stream`：`stage/log/stats/result/error/done`；400/429 |
| `/api/analyze-text` | trace-engine-web | POST | 计算 | `{text, mode, config?}` | `{success, cached, traceId, data:{id, result, reportPath, resultPath}}`；400/429/500 |
| `/api/analyze-file` | trace-engine-web | POST | 计算 | `multipart/form-data`：`file, mode, config?` | 同上 |
| `/api/cancel/:id` | trace-engine-web | POST | 治理 | path: id | `{success, cancelled, reason}`；404 |
| `/api/retry/:id` | trace-engine-web | POST | 计算 | path: id | `{success, originalId, newId, data}`；400/404/500 |
| `/api/run` | trace-to-edm | POST | 转发 | `{csv_path?, mode?, trace_mode?}` | SSE 流：`start/progress/warn/log/done/error`；`trace_mode` 取值 `light`/`deep`，决定 TRACE 分析使用 LIGHT 还是 DEEP 模式（默认 `light`） |
| `/api/replay` | trace-to-edm | POST | 转发 | `{csv_path?, replay_all?}` | SSE 流：同上 |
| `/api/replay-all` | trace-to-edm | POST | 转发 | — | SSE 流（实际由 `/api/replay` 复用） |
| `/api/edm/trigger` | trace-to-edm | POST | 计算+转发 | `{target?, q?, time_start?, time_end?, predict_window?}` | `{success, ...result}` 或 `{success, output, stderr}` |
| `/api/pipeline/run` | trace-to-edm | POST | 计算+储存 | `{trace_mode?}` | SSE 流：聚合回填+文本管线；`trace_mode` 取值 `light`/`deep`，决定 TRACE 分析使用 LIGHT 还是 DEEP 模式（默认 `light`，Round 13 P2-13.6 修缮后支持） |
| `/api/replay-uuids` | trace-to-edm | POST | 转发 | `{uuids: string[]}` | SSE 流：`start/progress/warn/log/done/error` |

**SSE 错误反馈统一规范**（治理建议）：
- `event: error` 携带 `{message, code?, retryable?}`；
- `event: done` 携带 `{job_id, success, trajectory_rows?, edm_ready?}`；
- 服务端在响应头写入 `retry: 5000`（trace-engine-web 已实现；其余两个项目待补）。

### 2.4 L4 — 历史层（History / Archive / Compare / Export）

| 端点 | 服务 | 方法 | 数据流 | 请求契约 | 响应契约 |
|------|------|------|--------|---------|---------|
| `/api/history` | edm-takens-web | GET | 只读 | query: limit=50 | `[{task_id, updated_at, images[], has_config}]` |
| `/api/history/{task_id}/archive` | edm-takens-web | POST | 储存 | path: task_id | `{task_id, archived: true, zip}`；404/500 |
| `/api/history/{task_id}/download` | edm-takens-web | GET | 只读 | path: task_id | `application/zip`；404 |
| `/api/history/{task_id}` | edm-takens-web | DELETE | 储存 | path: task_id | `{task_id, deleted:{result_dir, zip}}`；404 |
| `/api/history/cleanup` | edm-takens-web | POST | 治理 | query: days=30, max_size_mb?, dry_run? | `{dry_run, days, removed[], removed_count, size_deleted[], size_deleted_count}` |
| `/api/archives` | edm-takens-web | GET | 只读 | — | `{archives:[{task_id, filename, size_bytes, updated_at}]}` |
| `/api/archives/{task_id}/restore` | edm-takens-web | POST | 储存 | path: task_id | `{task_id, restored: true, path}`；404/409/500 |
| `/api/archives/{task_id}` | edm-takens-web | DELETE | 储存 | path: task_id | `{task_id, deleted: true}`；404/500 |
| `/api/history/batch` | edm-takens-web | POST | 储存 | `{action: archive\|delete\|download, task_ids[]}` | `{action, results[{task_id, success, detail}]}` 或 `application/zip` |
| `/api/history/compare` | edm-takens-web | POST | 只读 | `{task_ids:[id1,id2]}` 或 `{left_id, right_id}` | `{task_ids, left_task, right_task, summaries}` |
| `/api/history/{task_id}/export/json` | edm-takens-web | GET | 只读 | path: task_id | `application/json`（attachment） |
| `/api/history/{task_id}/export/csv` | edm-takens-web | GET | 只读 | path: task_id | `text/csv`（attachment, UTF-8 BOM） |
| `/api/jobs` | trace-engine-web | GET | 只读 | — | `{success, active[], history[], cacheSize}` |
| `/api/jobs/export` | trace-engine-web | GET | 只读 | — | `application/json` attachment |
| `/api/jobs/clear` | trace-engine-web | POST | 治理 | — | `{success, message}` |
| `/api/jobs/:id` | trace-engine-web | GET | 只读 | path: id | `{success, id, active, history, resultPath, reportPath}`；404 |
| `/api/result/:id` | trace-engine-web | GET | 只读 | path: id | `application/json`；400/404 |
| `/api/report/:id` | trace-engine-web | GET | 只读 | path: id | `text/markdown; charset=utf-8`；400/404 |
| `/api/jobs` | trace-to-edm | GET | 只读 | — | `{active[], history[]}` |

### 2.5 L5 — 治理层（Admin / Cleanup / Audit）

| 端点 | 服务 | 方法 | 数据流 | 请求契约 | 响应契约 |
|------|------|------|--------|---------|---------|
| `/api/admin/cleanup` | trace-engine-web | POST | 治理 | — | `{success, message, cleaned}`（受 auth 中间件保护） |
| `/api/history/cleanup` | edm-takens-web | POST | 治理 | 见 L4 | 见 L4 |
| `/api/jobs/clear` | trace-engine-web | POST | 治理 | — | 见 L4 |
| `/api/queue` | trace-engine-web | GET | 只读 | — | `{success, active[], queued[], maxConcurrent}` |
| `/api/metrics` | trace-engine-web | GET | 只读 | — | `{success, activeJobs, queuedJobs, cacheSize, jobHistoryTotal, statusCounts, skillReady, llamaWorkerReady, llamaWorkerBusy, uptimeSeconds, timestamp}` |
| `/api/models/activate` | trace-to-edm | POST | 治理 | 见 L2 | 见 L2 |
| `/api/dataset/clear-processed` | trace-to-edm | POST | 治理 | — | `{success: true}` |
| `/api/dataset/reset` | trace-to-edm | POST | 治理 | — | `{success: true}` |
| `/api/trajectory/clear` | trace-to-edm | POST | 治理 | — | `{success: true, rows: 0}` |

---

## 3. 跨项目 API 契约

四个跨项目契约是当前架构耦合最深的部位，微服务化必须先稳定这些接口。

### 3.1 trace-engine-web → trace-engine：subprocess + JSON Lines 契约

**调用方向**：`trace-engine-web/services/analysis.js` 调用 `trace-engine-web/py_bridge.py`。

**调用方式**：
```javascript
const py = spawn(CONFIG.pythonCmd, [
  pyScript, '--mode', mode, '--config', cfg, '--output-id', outputId,
], { cwd: CONFIG.skillDir, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
py.stdin.write(text, 'utf-8');   // 文本经 stdin 传入（避免命令行长度限制）
py.stdin.end();
```

**stdout 契约（JSON Lines，每行一个事件）**：
```jsonl
{"type":"stage","stage":"tokenize","progress":0.1}
{"type":"log","level":"info","message":"..."}
{"type":"stats","label":"...","rate":12.3,"processed_pairs":100,"total_pairs":500,"remaining_seconds":32}
{"type":"result","data":{ /* result_schema.json 完整结构 */ }}
{"type":"error","message":"...","code":"VALIDATION_FAILED"}
```

**stderr**：仅用于诊断日志，不参与协议。

**退出码**：`0` 成功；`非 0` 失败（已通过 `type: error` 事件预告）。

**结果文件**：`work/outputs/{id}/result.json` + `work/outputs/{id}/report.md`，由 `result_schema.json` 校验。

### 3.2 trace-to-edm → bridge.py：subprocess + SSE 转发契约

**调用方式**：
```javascript
const args = [BRIDGE_SCRIPT, '--input', inputPath, '--mode', traceMode, '--verbose'];
const proc = spawn(PYTHON_CMD, args, { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
```

**stdout 解析规则**（在 `server.js` 中已固化）：
- 含 `✓ 完成` / `批量处理完成` → 转为 SSE `event: progress`
- 含 `⚠` / `❌` → 转为 SSE `event: warn`
- 其他非空行 → 转为 SSE `event: log`
- 进程结束后读 `narrative_meta_trajectories.csv` 计算 `trajectory_rows` 与 `edm_ready`，发 `event: done`

**stdout JSON 提取规则**（用于 `/api/edm/trigger`）：
```javascript
const firstBrace = stdout.indexOf('{');
const lastBrace = stdout.lastIndexOf('}');
const jsonStr = stdout.slice(firstBrace, lastBrace + 1);
const result = JSON.parse(jsonStr);
```
> 风险：若 Python 日志中混入 `{...}` 字符会污染 JSON 提取。**微服务化建议**：bridge.py 应在结束时输出哨兵行 `===BRIDGE_RESULT_BEGIN===` / `===BRIDGE_RESULT_END===`，server.js 只在两哨兵之间提取 JSON。

### 3.3 trace-to-edm → edm-takens-web：HTTP 契约（规划中）

**调用方向**：trace-to-edm 在 `/api/edm/trigger` 收到请求后，应改为调用 edm-takens-web 的 `POST /api/analyze/jobs`（当前实现是直接 spawn bridge.py，未来切换为 HTTP）。

**HTTP 契约**：
```http
POST /api/analyze/jobs HTTP/1.1
Host: localhost:8000
Content-Type: multipart/form-data; boundary=----xyz

------xyz
Content-Disposition: form-data; name="filename"

narrative_meta_trajectories.csv
------xyz
Content-Disposition: form-data; name="target_col"

ate
------xyz
Content-Disposition: form-data; name="intensity"

medium
------xyz--
```

**响应**：
```json
{
  "job_id": "1784205758_2a15d2b4",
  "status": "pending",
  "profile": { "level": "medium", "params": { "q": 3, "max_e": 8, "auto_fix": true } },
  "data_quality_warning": null
}
```

**轮询**：`GET /api/analyze/jobs/{job_id}` 直至 `status: done | error`，或订阅 `GET /api/analyze/jobs/{job_id}/stream` 拿 NDJSON 流。

**降级策略**：若 edm-takens-web 不可达，trace-to-edm 应回退到当前的 `spawn bridge.py` 模式，并在 `/api/status` 中标注 `edm_backend: "degraded"`。

### 3.4 edm-takens-web → edm-takens：Python import 契约

**调用方式**：`edm-takens-web/backend/edmtakens/` 是 `edm-takens/src/` 的镜像副本，通过 `import` 直接调用。

**关键模块契约**：
| 模块 | 入口函数 | 输入 | 输出 |
|------|---------|------|------|
| `pipeline.py` | `run(config)` | `Config` 对象 | `Result` 对象（含 `summary, images, task_id`） |
| `ccm_causality.py` | `run_ccm(df, target, ...)` | DataFrame | `{rho, p_value, ...}` |
| `_edm_bridge.py` | `EmbedDimension(data, lib, pred, ...)` | DataFrame | DataFrame(`E, rho`) |
| `edm_auditor.py` | `audit(result)` | Result | `AuditReport` |
| `final_interpretation.py` | `interpret(result)` | Result | `{narrative, confidence, caveats}` |

**微服务化建议**：当前镜像副本导致代码漂移风险（两份 `pipeline.py`）。Phase 2 应将 `edm-takens` 抽出为独立 pip 包或独立 FastAPI 服务，`edm-takens-web` 通过 `pip install` 或 HTTP 调用消费。

---

## 4. 前端鲁棒性设计

### 4.1 自适应比例方案

**现状审计**：
- `trace-engine-web/public/css/main.css`：已大量使用 `clamp()` + `vw/vh` + `dvh` + `@media (max-width: 1200px)`，是三项目中自适应最完善的。
- `edm-takens-web/frontend/src/style.css`：使用 `clamp()` + `vw`，缺 `dvh` 与 `@media` 断点。
- `trace-to-edm/public/css/main.css`：未盘点到 `clamp` 使用，自适应最弱。

**统一方案（CSS 三件套 + 容器查询）**：

```css
/* 1) 视口单位：优先 dvh（移动端动态视口高度），回退 vh */
.full-height {
  min-height: 100vh;
  min-height: 100dvh;
}

/* 2) 字号 / 间距 / 圆角：clamp(下限, 首选, 上限) */
.panel-title  { font-size: clamp(1.05rem, 1.6vw + 0.5rem, 1.35rem); }
.panel-body   { padding:   clamp(0.9rem, 1.7vw, 1.25rem); }
.gap-stack    { gap:       clamp(0.7rem, 1.5vw, 1.1rem); }

/* 3) 容器宽度：min(96vw, 1600px) 防止超宽屏拉伸 */
.container    { width: min(96vw, 1600px); margin-inline: auto; }

/* 4) 断点：三档（紧凑平板 / 桌面 / 宽屏） */
@media (max-width: 768px)  { .grid-main { grid-template-columns: 1fr; } }
@media (max-width: 1200px) { .grid-main { grid-template-columns: 1fr 1.4fr; } }
@media (min-width: 1601px) { .container  { width: min(90vw, 1920px); } }

/* 5) 容器查询（@container，2026 浏览器支持良好）—组件根据自身宽度自适应 */
.panel { container-type: inline-size; }
@container (max-width: 480px) {
  .panel .toolbar { flex-direction: column; align-items: stretch; }
}
```

**ResizeObserver 节流方案**（用于复杂图表/终端的高度跟随）：

```javascript
// 终端高度跟随父容器，避免出现滚动条嵌套
const terminal = document.getElementById('terminal');
const ro = new ResizeObserver(throttle((entries) => {
  for (const entry of entries) {
    const h = Math.max(180, Math.min(entry.contentRect.height, 600));
    terminal.style.maxHeight = `${h}px`;
  }
}, 100));
ro.observe(terminal.parentElement);
```

**图片/图表比例锁**（防止 SVG/PNG 被容器压扁）：
```css
.result-image {
  aspect-ratio: 16 / 9;
  width: 100%;
  height: auto;
  object-fit: contain;
}
```

### 4.2 网页关闭重连机制（核心需求）

**现状审计**：
- `trace-engine-web`：**已实现** SSE 断点续传。`sse.js` 维护 `lastSseEventId`，`app.js` 重连时通过 `Last-Event-ID` 请求头携带；服务端每个事件写 `id: N` 并发 `retry: 5000`。但 `currentJobId` 仅在内存中，刷新页面会丢失。
- `edm-takens-web`：**部分实现**。`main.js` 用 `setInterval(poll, 2000)` 做兜底轮询，stream 断开后会用 `GET /api/analyze/jobs/{job_id}` 恢复状态。但 `jobId` 也仅在内存中。
- `trace-to-edm`：**未实现**。SSE 流断开即丢失，`jobId` 仅在内存中，无 `Last-Event-ID` 支持。

#### 4.2.1 任务 ID 持久化（localStorage + IndexedDB 双层）

```javascript
// 持久化键命名规范：{service}:activeJob:{jobId}
// 例：trace-engine-web:activeJob:abc123
// 例：edm-takens-web:activeJob:1784205758_2a15d2b4

const JOB_STORE = {
  // 轻量元数据 → localStorage（快速恢复 UI 状态）
  saveMeta(jobId, meta) {
    localStorage.setItem(
      `edm:activeJob:${jobId}`,
      JSON.stringify({ ...meta, savedAt: Date.now() })
    );
    // 维护活跃 job 索引，便于启动时枚举
    const idx = JSON.parse(localStorage.getItem('edm:activeJobs') || '[]');
    if (!idx.includes(jobId)) {
      idx.push(jobId);
      localStorage.setItem('edm:activeJobs', JSON.stringify(idx));
    }
  },
  loadActiveJobs() {
    return JSON.parse(localStorage.getItem('edm:activeJobs') || '[]');
  },
  clearJob(jobId) {
    localStorage.removeItem(`edm:activeJob:${jobId}`);
    const idx = JSON.parse(localStorage.getItem('edm:activeJobs') || '[]');
    localStorage.setItem('edm:activeJobs', JSON.stringify(idx.filter(x => x !== jobId)));
  },

  // 大体量日志/结果 → IndexedDB（避免 localStorage 5MB 上限）
  async appendLog(jobId, line) {
    const db = await openDB();
    await db.add('logs', { jobId, line, ts: Date.now() });
  },
  async getLogs(jobId) {
    const db = await openDB();
    return db.getAllFromIndex('logs', 'byJob', jobId);
  },
  async saveResultSnapshot(jobId, result) {
    const db = await openDB();
    await db.put('results', { jobId, result, ts: Date.now() });
  },
};

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('edm-reconnect', 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('logs')) {
        const s = db.createObjectStore('logs', { autoIncrement: true });
        s.createIndex('byJob', 'jobId');
      }
      if (!db.objectStoreNames.contains('results')) {
        db.createObjectStore('results', { keyPath: 'jobId' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
```

**生命周期钩子**：
```javascript
// 提交任务时：先持久化 jobId，再发请求
async function submitJob(payload) {
  const jobId = crypto.randomUUID();
  JOB_STORE.saveMeta(jobId, { service: 'trace-engine-web', mode: payload.mode, textLength: payload.text.length });
  // ... 发起 fetch /api/analyze-stream
  return jobId;
}

// 任务完成时：清理持久化
function onJobDone(jobId) {
  JOB_STORE.clearJob(jobId);
}

// 页面加载时：枚举未完成的 job，逐个恢复
window.addEventListener('load', () => {
  const active = JOB_STORE.loadActiveJobs();
  if (active.length) {
    showToast(`检测到 ${active.length} 个未完成任务，正在恢复...`, 'info');
    active.forEach(jobId => resumeJob(jobId));
  }
});
```

#### 4.2.2 重连后自动恢复任务状态轮询

```javascript
async function resumeJob(jobId) {
  const meta = JSON.parse(localStorage.getItem(`edm:activeJob:${jobId}`) || 'null');
  if (!meta) { JOB_STORE.clearJob(jobId); return; }

  // 1. 先做单次状态查询，判断任务是否还存在
  let status;
  try {
    const r = await fetch(`/api/analyze/jobs/${encodeURIComponent(jobId)}`);
    if (r.status === 404) {
      // 任务在服务端已丢失（服务重启清空了 job_store）
      showToast(`任务 ${jobId.slice(0, 8)} 已在服务端丢失`, 'warn');
      JOB_STORE.clearJob(jobId);
      // 尝试从 IndexedDB 恢复结果快照
      const db = await openDB();
      const snap = await new Promise(res => {
        const tx = db.transaction('results').objectStore('results').get(jobId);
        tx.onsuccess = () => res(tx.result);
        tx.onerror = () => res(null);
      });
      if (snap) renderResult(snap.result);
      return;
    }
    status = await r.json();
  } catch (e) {
    // 网络仍不可达，5s 后重试
    setTimeout(() => resumeJob(jobId), 5000);
    return;
  }

  // 2. 根据 status 决定后续动作
  if (status.status === 'done') {
    renderResult(status.result);
    JOB_STORE.clearJob(jobId);
  } else if (status.status === 'error') {
    showToast(`任务 ${jobId.slice(0, 8)} 已失败: ${status.error}`, 'error');
    JOB_STORE.clearJob(jobId);
  } else {
    // pending / running：恢复轮询 + 重新订阅 SSE
    setRunning(true);
    startPolling(jobId);
    resubscribeStream(jobId, meta);
  }
}
```

#### 4.2.3 SSE 断点续传（Last-Event-ID + 服务端事件缓冲）

**服务端改造**（以 trace-to-edm 为例，目前最弱）：

```javascript
// 新增：每个 jobId 对应一个环形缓冲区，保留最近 200 个事件
const eventBuffers = new Map(); // jobId → { nextId: 0, events: [{id, event, data}] }

function emitSSEWithId(res, jobId, event, data) {
  const buf = eventBuffers.get(jobId) || { nextId: 0, events: [] };
  const id = buf.nextId++;
  buf.events.push({ id, event, data });
  if (buf.events.length > 200) buf.events.shift();
  eventBuffers.set(jobId, buf);

  res.write(`id: ${id}\nevent: ${event}\ndata: ${JSON.stringify({ _event: event, ...data })}\n\n`);
}

// 新增：/api/stream/:id 端点支持 Last-Event-ID
app.get('/api/stream/:id', (req, res) => {
  const jobId = req.params.id;
  const lastId = parseInt(req.get('Last-Event-ID') || '-1', 10);

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });
  res.write('retry: 5000\n\n'); // 告知浏览器 5s 后自动重连

  // 1. 回放缓冲区中 lastId 之后的事件
  const buf = eventBuffers.get(jobId);
  if (buf) {
    for (const ev of buf.events) {
      if (ev.id > lastId) {
        res.write(`id: ${ev.id}\nevent: ${ev.event}\ndata: ${JSON.stringify({ _event: ev.event, ...ev.data })}\n\n`);
      }
    }
  }

  // 2. 若任务已结束，发 done 后关闭
  const job = activeJobs.get(jobId);
  if (!job) {
    const hist = jobHistory.find(h => h.id === jobId);
    if (hist) {
      res.write(`event: done\ndata: ${JSON.stringify({ job_id: jobId, success: hist.status === 'completed' })}\n\n`);
    }
    return res.end();
  }

  // 3. 否则接管活跃任务的 SSE 转发（替换旧 res 引用）
  job.res = res;
  res.on('close', () => { /* 客户端断开，保留 job 与缓冲区，等待重连 */ });
});
```

**客户端配合**（沿用 trace-engine-web 的 `sse.js` 模式，向另两个项目推广）：

```javascript
let lastEventId = null;
let currentRes = null;

async function resubscribeStream(jobId, meta) {
  const headers = { 'Content-Type': 'application/json' };
  if (lastEventId != null) headers['Last-Event-ID'] = String(lastEventId);

  currentRes = await fetch(`/api/stream/${jobId}`, { headers });
  const reader = currentRes.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      // 流断开：5s 后自动重连（fetch 不会像 EventSource 那样自动重连）
      setTimeout(() => resubscribeStream(jobId, meta), 5000);
      return;
    }
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop();
    for (const block of blocks) {
      const ev = parseSSEBlock(block); // 解析 id: / event: / data:
      if (ev?.id != null) lastEventId = ev.id;
      dispatchSSEEvent(ev);
    }
  }
}
```

#### 4.2.4 结果数据缓存（避免重复计算）

**三层缓存策略**：

| 层 | 位置 | 用途 | TTL |
|---|------|------|-----|
| L1 内存 | 浏览器 JS 变量 | 单次会话内切换页面不重新请求 | 标签页生命周期 |
| L2 持久 | IndexedDB `results` store | 网页关闭后重开仍可秒开最近结果 | 7 天（LRU 清理） |
| L3 服务端 | `resultCache` (trace-engine-web) / `RESULTS_DIR` (edm-takens-web) | 跨用户/跨设备共享 | 服务端策略 |

```javascript
async function fetchResult(jobId) {
  // L1
  if (resultCache.has(jobId)) return resultCache.get(jobId);
  // L2
  const db = await openDB();
  const snap = await new Promise(res => {
    const tx = db.transaction('results').objectStore('results').get(jobId);
    tx.onsuccess = () => res(tx.result?.result);
    tx.onerror = () => res(null);
  });
  if (snap) { resultCache.set(jobId, snap); return snap; }
  // L3
  const r = await fetch(`/api/result/${jobId}`);
  if (!r.ok) return null;
  const result = await r.json();
  resultCache.set(jobId, result);
  // 写回 L2
  await new Promise(res => {
    const tx = db.transaction('results', 'readwrite');
    tx.objectStore('results').put({ jobId, result, ts: Date.now() });
    tx.oncomplete = () => res();
  });
  return result;
}
```

### 4.3 错误恢复策略矩阵

| 故障场景 | 检测方式 | 客户端响应 | 服务端响应 |
|---------|---------|-----------|-----------|
| **网络瞬断**（<5s） | `fetch` reject `TypeError: Failed to fetch` | 指数退避重试（1s → 2s → 5s → 10s），最多 5 次 | — |
| **网络长断**（>30s） | 重试超 5 次仍失败 | 显示"网络断开"横幅，转为纯轮询模式（每 10s 一次 `GET /api/jobs/{id}`） | — |
| **服务重启**（job 丢失） | `GET /api/jobs/{id}` 返回 404 | 从 IndexedDB 恢复结果快照；提示"任务因服务重启丢失" | 服务启动时清理 stale `activeJobs` |
| **SSE 流断开** | `reader.read()` 返回 `done: true` | 5s 后用 `Last-Event-ID` 重连；重连失败转轮询 | 保留 `eventBuffers` 5 分钟，超时清理 |
| **任务卡死**（status 长期 `running`） | 轮询 N 次状态不变 | 提供"强制取消"按钮 → `POST /api/cancel/:id` | 服务端应有任务超时机制（trace-engine-web 已有 `CONFIG.outputTtlMs`） |
| **结果文件损坏** | `GET /api/result/:id` 返回 500 或 JSON 解析失败 | 回退到 L2 缓存；提示"结果已损坏，请重试" | 服务端启动时校验 `result.json` schema |
| **并发限流**（429） | HTTP 429 | 显示"服务器繁忙，已加入队列"；轮询 `/api/queue` 等位 | — |

---

## 5. 微服务化实施路线

### Phase 1：API 契约文档化 + OpenAPI Schema（1-2 周）

**目标**：本文档落地为可机读的 OpenAPI 3.1 规范，所有端点纳入版本控制。

**动作项**：
1. 为 edm-takens-web 启用 FastAPI 自带的 OpenAPI 生成（`/docs`、`/openapi.json`），补充 Pydantic 模型。
2. 为 trace-engine-web 与 trace-to-edm 编写手写 `openapi.yaml`，覆盖所有 88 端点。
3. 统一错误响应格式：
   ```json
   { "success": false, "error": "...", "code": "VALIDATION_FAILED", "field": "filename", "traceId": "..." }
   ```
4. 落地 `result_schema.json` 与 `bridge_schema.json` 的 JSON Schema 校验（trace-engine-web 已有，需推广到另两个项目）。

### Phase 2：跨项目 API 网关（2-3 周）

**目标**：引入统一入口（如 `localhost:8080`），按路径前缀路由到三个后端服务。

**网关路由表**：
| 网关路径 | 转发目标 | 备注 |
|---------|---------|------|
| `/edm/*` | `localhost:8000/*` | edm-takens-web |
| `/trace/*` | `localhost:3000/*` | trace-engine-web |
| `/bridge/*` | `localhost:3100/*` | trace-to-edm |
| `/health` | 并发查询三个服务的 `/api/health` | 聚合健康度 |

**额外能力**：
- 统一 CORS、统一鉴权（接 auth 中间件）、统一日志（traceId 透传）。
- 统一 SSE 代理（注意禁用 nginx/网关的缓冲：`X-Accel-Buffering: no` 已在 trace-engine-web 设置）。

### Phase 3：服务发现 + 健康检查（1-2 周）

**目标**：网关不再硬编码端口，而是通过服务注册表动态发现。

**方案**：
- 轻量方案：每个服务启动时向 `localhost:8500/v1/agent/service/register` 注册（Consul 单节点）。
- 极简方案：每个服务在 `/api/health` 暴露 `service`、`version`、`port` 字段；网关启动时扫描 `localhost:3000-3200, 8000`。

**健康检查规范**：
- Liveness：`GET /api/health` 返回 200 即存活。
- Readiness：`status === "healthy"` 才接收流量；`degraded` 仍存活但降级（如 Python 环境异常时只读不写）。

### Phase 4：前端重连机制实施（2-3 周）

**目标**：三个前端面板统一实现 4.2 节描述的完整重连能力。

**优先级**：
1. **P0**：trace-to-edm 前端补齐 `Last-Event-ID` + `jobId` 持久化（当前最弱）。
2. **P0**：edm-takens-web 前端补齐 `jobId` 持久化（已有轮询兜底，只需补 localStorage）。
3. **P1**：trace-engine-web 前端补齐 `jobId` 持久化（已有 Last-Event-ID，只需补 localStorage）。
4. **P1**：三个前端统一抽取 `reconnect.js` 公共模块（避免三份重复实现）。
5. **P2**：服务端 `eventBuffers` 落地（trace-to-edm 与 edm-takens-web 需新建；trace-engine-web 已有部分支持）。

---

## 6. 与现有架构的兼容性

### 6.1 端点保护承诺

| 项目 | 现有端点数 | 微服务化后保留 | 备注 |
|------|-----------|--------------|------|
| edm-takens-web | 29 | 29 | 仅补 OpenAPI 文档，不改路由 (Round 19 校正: 25→29) |
| trace-engine-web | 26 | 26 | 仅补 OpenAPI 文档，不改路由 (ROUND26 校正: 24→26, 含 batch-delete/export/md 等) |
| trace-to-edm | 33 | 33 | 仅补 OpenAPI 文档，不改路由 (ROUND26 校正: 31→33, 与 server.js header 一致) |
| **合计** | **88** | **88** | 网关层只做转发，不重写路径 (ROUND26 校正: 84→88) |

### 6.2 渐进式策略

```
当前状态：3 个独立服务，浏览器分别访问 :3000 / :3100 / :8000
                ↓ Phase 1
契约化：3 个服务 + OpenAPI 文档（路由不变）
                ↓ Phase 2
网关化：浏览器只访问 :8080，网关按前缀转发（后端路由不变）
                ↓ Phase 3
服务发现：网关动态发现后端（后端路由不变，只多注册逻辑）
                ↓ Phase 4
前端重连：三个前端统一 reconnect.js（后端路由不变，只多 /api/stream/:id 端点）
                ↓ 未来
真正的微服务拆分：按 L1-L5 层级抽离独立服务（如 history-service、dataset-service），
                  旧端点保留为兼容代理，新端点走新服务。这一步不在本路线图内。
```

### 6.3 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 网关引入单点故障 | 网关仅做转发，可随时绕过直连后端；前端保留 `API_PREFIX` 可配置 |
| SSE 经网关被缓冲 | 网关必须设置 `X-Accel-Buffering: no`、`Cache-Control: no-cache`、禁用 gzip |
| 服务发现依赖 Consul | 极简方案下用静态配置 fallback，Consul 不可用时降级到硬编码 |
| `eventBuffers` 内存膨胀 | 每个 jobId 缓冲上限 200 事件，5 分钟未活跃则清理；总内存上限 100MB |
| IndexedDB 配额不足 | 写入前检查 `navigator.storage.estimate()`；超过 80% 时 LRU 清理 |
| 跨标签页重复恢复 | 用 `BroadcastChannel` 协调：第一个标签页恢复 job 后广播，其他标签页放弃 |
| 旧前端缓存与新契约冲突 | localStorage 键加 schema 版本号：`edm:activeJob:v1:{jobId}` |

---

## 7. 轨迹表诊断字段与 threshold 默认值

### 7.1 轨迹表诊断字段（trace_status / trace_mode / trace_error）

**背景**: Round 13 P0-13.1 修缮后，trace-to-edm 的 `bridge.py` 在 `process_single_text` 中显式写入三个诊断字段到 `narrative_meta_trajectories.csv`，让下游（edm-takens-web 与前端）能正确区分"LIGHT 模式不跑六战士"与"DEEP 模式跑失败"，避免 §13.0 描述的"7 列全 0 误判算法失败"问题。

**字段定义**:

| 字段 | 类型 | 取值 | 含义 |
|------|------|------|------|
| `trace_status` | string | `OK` / `FAILED` / `PARTIAL` / `EXTRACT_FAILED` / `SKIPPED` / `LEGACY` | TRACE 分析状态。`OK`=完全成功；`FAILED`=TRACE 子进程失败；`PARTIAL`=部分成功（如六战士部分降级）；`EXTRACT_FAILED`=L1 提取失败；`SKIPPED`=跳过 TRACE；`LEGACY`=历史行补标记（Round 13 前的数据） |
| `trace_mode` | string | `light` / `deep` / `unknown` | TRACE 分析模式。`light`=LIGHT 模式（不跑六战士）；`deep`=DEEP 模式（完整六战士诊断）；`unknown`=历史行无模式标记 |
| `trace_error` | string | 错误详情（最长 300 字符） | TRACE 失败时的错误详情，便于下游诊断。前端表格中截断显示 40 字符，完整内容放 `title` tooltip |

**前端渲染契约**（trace-to-edm `public/js/app.js`）:
- `preferredCols` 末尾追加 `trace_status`、`trace_mode`、`trace_error` 三列
- `layerMap` 归入 `trace` 分组
- `trace_status` 按状态值着色（`tstat-*` CSS 类）：
  - `OK` = 绿色
  - `FAILED` = 红色
  - `PARTIAL` = 黄色
  - `EXTRACT_FAILED` = 橙色
  - `SKIPPED` = 灰色
- `trace_error` 截断 40 字符防单元格溢出，完整 300 字符放 `title` tooltip

**关联端点**: `/api/run`、`/api/pipeline/run`、`/api/replay-uuids` 的 SSE `done` 事件携带 `trajectory_rows`，CSV 中即包含上述三列。

### 7.2 threshold 默认值（双轨制）

**背景**: §13.4.3 文档歧义修正后，threshold 默认值明确为双轨制。

**权威来源**:
- [presets.yaml:23](../TRACE Engine(EDM-Takens CCM)/trace-engine/examples/counterfactual_hybrid/presets.yaml) `threshold: 0.03`，注释 "默认取模型文档推荐标准值 0.03"
- [TRACE Interpretation Dictionary.md:34](../TRACE Engine(EDM-Takens CCM)/trace-engine-web/TRACE Interpretation Dictionary.md) "Web 默认值 0.03 适合通用文本"

**取值规则**:

| 场景 | threshold | 说明 |
|------|-----------|------|
| 通用文本（standard 预设） | **0.03** | 模型文档推荐标准值，匹配 `ΔNLL ~ 0–0.16` 的 99% 置信区 |
| LLaMA/llama 预设（V4 过拟合模型） | **0.01** | V4 过拟合模型 ΔNLL 偏低，需更严格过滤防止假阳性 |
| SUPER 模式（trace-engine-web） | **0.01** | SUPER 模式使用 LLaMA 模型，沿用 llama 预设的 0.01 |

**API 契约**:
- `GET /api/config`（trace-engine-web）返回的 `bridgeParamSchema.threshold.default = 0.03`，`superBridgeParamSchema.threshold.default = 0.01`
- `GET /api/presets`（trace-engine-web）返回的 `standard.trace2dowhy.threshold = 0.03`，`llama.trace2dowhy.threshold = 0.01`
- 前端 LIGHT/DEEP 模式默认 0.03，SUPER 模式默认 0.01

**注意**: `test_presets.py` 4 处断言 `0.03`，盲改为 0.01 会破坏测试套件。代码无需修改，文档与 memory 已修正歧义。

---

## 附录 A：88 端点全量索引（按服务 + 层级）

### A.1 edm-takens-web（29 端点）

| 层级 | 端点 | 方法 | 文件 |
|------|------|------|------|
| L1 | `/api/health` | GET | datasets.py |
| L2 | `/api/datasets` | GET | datasets.py |
| L2 | `/api/upload` | POST | datasets.py |
| L2 | `/api/datasets/{filename}/columns` | GET | datasets.py |
| L2 | `/api/datasets/{filename}/recommend` | GET | datasets.py |
| L2 | `/api/datasets/{filename}/quality` | GET | datasets.py |
| L2 | `/api/datasets/{filename}/embed_curve` | GET | datasets.py |
| L3 | `/api/analyze/jobs` | POST | analyze.py |
| L3 | `/api/analyze/jobs/{job_id}` | GET | analyze.py |
| L3 | `/api/analyze/jobs/{job_id}/stream` | GET | analyze.py |
| L3 | `/api/analyze` | POST | analyze.py |
| L3 | `/api/analyze/stream` | GET | analyze.py |
| L3 | `/api/results/{image_path}` | GET | analyze.py |
| L4 | `/api/history` | GET | history.py |
| L4 | `/api/history/{task_id}` | GET | history.py |
| L4 | `/api/history/{task_id}/archive` | POST | history.py |
| L4 | `/api/history/{task_id}/download` | GET | history.py |
| L4 | `/api/history/{task_id}` | DELETE | history.py |
| L5 | `/api/history/cleanup` | POST | history.py |
| L4 | `/api/archives` | GET | history.py |
| L4 | `/api/archives/{task_id}/restore` | POST | history.py |
| L4 | `/api/archives/{task_id}/preview` | GET | history.py |
| L4 | `/api/archives/{task_id}` | DELETE | history.py |
| L4 | `/api/history/batch` | POST | history.py |
| L4 | `/api/history/compare` | POST | history.py |
| L4 | `/api/history/{task_id}/export/json` | GET | history.py |
| L4 | `/api/history/{task_id}/export/csv` | GET | history.py |
| L4 | `/api/history/{task_id}/export/md` | GET | history.py |
| L4 | `/api/history/{task_id}/export/html` | GET | history.py |

> 注：`GET /` 与 `GET /{path:path}`（api.py 中的 SPA 静态托管回退）不计入 29 个 API 端点之列，与 TECHNICAL.md §3.0 一致。

### A.2 trace-engine-web（26 端点）

| 层级 | 端点 | 方法 | 文件 |
|------|------|------|------|
| L1 | `/` | GET | server.js（express.static 前端页面） |
| L1 | `/api/health` | GET | system.js |
| L1 | `/api/config` | GET | system.js |
| L1 | `/api/version` | GET | system.js |
| L1 | `/api/schema` | GET | system.js |
| L1 | `/api/presets` | GET | system.js |
| L1 | `/api/models` | GET | system.js |
| L5 | `/api/queue` | GET | system.js |
| L5 | `/api/metrics` | GET | system.js |
| L3 | `/api/analyze-stream` | GET | analysis.js |
| L3 | `/api/analyze-stream` | POST | analysis.js |
| L3 | `/api/analyze-text` | POST | analysis.js |
| L3 | `/api/analyze-file` | POST | analysis.js |
| L3 | `/api/cancel/:id` | POST | analysis.js |
| L3 | `/api/result/:id` | GET | analysis.js |
| L3 | `/api/report/:id` | GET | analysis.js |
| L3 | `/api/retry/:id` | POST | analysis.js |
| L4 | `/api/jobs` | GET | jobs.js |
| L4 | `/api/jobs/export` | GET | jobs.js |
| L4 | `/api/jobs/:id` | GET | jobs.js |
| L4 | `/api/jobs/:id/detail` | GET | jobs.js |
| L4 | `/api/jobs/:id/export/md` | GET | jobs.js |
| L5 | `/api/jobs/clear` | POST | jobs.js |
| L5 | `/api/jobs/batch-delete` | POST | jobs.js |
| L5 | `/api/jobs/:id` | DELETE | jobs.js |
| L5 | `/api/admin/cleanup` | POST | admin.js |

### A.3 trace-to-edm（33 端点）

> 行号同步至 2026-07-28（server.js 端点计数 33，含 /api/health、/api/version、/api/orthogonality、/api/inputs、/api/edm/poll/:jobId、/api/trajectory/export/md、/api/trajectory/report、/api/work-uuid/:uuid/text 等端点）。

| 层级 | 端点 | 方法 | 行号 |
|------|------|------|------|
| L1 | `/api/health` | GET | 1035 |
| L1 | `/api/version` | GET | 1041 |
| L1 | `/api/status` | GET | 1053 |
| L1 | `/api/orthogonality` | GET | 1106 |
| L2 | `/api/trajectory` | GET | 1128 |
| L5 | `/api/trajectory/clear` | POST | 1133 |
| L4 | `/api/trajectory/export/md` | GET | 1154 |
| L4 | `/api/trajectory/report` | GET | 1173 |
| L3 | `/api/run` | POST | 1192 |
| L3 | `/api/replay` | POST | 1285 |
| L3 | `/api/edm/trigger` | POST | 1374 |
| L3 | `/api/edm/poll/:jobId` | GET | 1460 |
| L4 | `/api/jobs` | GET | 1495 |
| L4 | `/api/inputs` | GET | 1531 |
| L2 | `/api/dataset` | GET | 1553 |
| L2 | `/api/dataset/add` | POST | 1562 |
| L2 | `/api/dataset/add-text` | POST | 1572 |
| L2 | `/api/dataset/remove` | POST | 1592 |
| L5 | `/api/dataset/clear-processed` | POST | 1597 |
| L5 | `/api/dataset/reset` | POST | 1602 |
| L2 | `/api/dataset/update-ts` | POST | 1607 |
| L3 | `/api/pipeline/run` | POST | 1754 |
| L2 | `/api/models` | GET | 1845 |
| L5 | `/api/models/activate` | POST | 1859 |
| L2 | `/api/projects` | GET | 1898 |
| L2 | `/api/projects` | POST | 1919 |
| L2 | `/api/projects/activate` | PUT | 1933 |
| L2 | `/api/projects/:name` | DELETE | 1948 |
| L2 | `/api/work-scan` | GET | 1964 |
| L2 | `/api/work-uuid/:uuid` | DELETE | 1973 |
| L5 | `/api/work-clean` | POST | 1996 |
| L3 | `/api/replay-uuids` | POST | 2024 |
| L2 | `/api/work-uuid/:uuid/text` | GET | 2098 |

---

## 附录 B：现有 SSE 重连能力盘点

| 能力 | trace-engine-web | edm-takens-web | trace-to-edm |
|------|------------------|----------------|--------------|
| 服务端每个事件写 `id: N` | ✅ | ❌（NDJSON 无 id） | ❌ |
| 服务端发 `retry: 5000` | ✅ | ❌ | ❌ |
| 客户端解析 `id:` 行 | ✅（sse.js） | ❌ | ❌ |
| 客户端重连时发 `Last-Event-ID` 头 | ✅（app.js） | ❌ | ❌ |
| 客户端轮询兜底 | ❌ | ✅（2s 间隔） | ❌ |
| `jobId` 持久化到 localStorage | ❌ | ❌ | ❌ |
| 结果快照缓存到 IndexedDB | ❌ | ❌ | ❌ |
| 服务端事件缓冲区 | ❌（每次重连从头开始） | ❌ | ❌ |

> **结论**：trace-engine-web 的 SSE 续传是最成熟的，但缺少任务持久化；另两个项目几乎从零开始。Phase 4 的工作量主要集中在 trace-to-edm 与 edm-takens-web。

---

## 附录 C：CSS 自适应能力盘点

| 项目 | `clamp()` 用量 | `vw/vh/dvh` 用量 | `@media` 断点数 | 容器查询 | 评级 |
|------|--------------|------------------|---------------|---------|------|
| trace-engine-web | 30+ | 20+ | 1（1200px） | ❌ | B+（最完善） |
| edm-takens-web | 15+ | 10+ | 0 | ❌ | B（缺断点） |
| trace-to-edm | 0 | 0 | 0 | ❌ | C（需重做） |

**统一目标**：所有项目达到 A 级——`clamp()` 全覆盖 + 3 档 `@media` 断点（768/1200/1601）+ 容器查询 + `ResizeObserver` 节流。

---

## 附录 D：外部依赖项 — Cloudflare Tunnel（cloudflared）

### D.1 依赖定位

五大项目中具备 Web 功能的三个项目（`edm-takens-web` / `trace-engine-web` / `trace-to-edm`）均提供了基于 **cloudflared** 的隧道启动脚本，用于将本地服务暴露到公网（临时 trycloudflare 域名），便于远程访问、移动端访问或第三方 webhook 回调测试。

| 项目 | 隧道脚本 | 暴露端口 | 后端启动方式 |
|------|---------|---------|-------------|
| edm-takens-web | `启动隧道.bat` | 5173（Vite 前端） | `python start_mvp.py` |
| trace-engine-web | `启动隧道.bat` | 3000~3020（动态探测） | `powershell -File start.ps1` |
| trace-to-edm | `启动隧道.bat` + `启动隧道.ps1` | 3100~3120（动态探测） | `node server.js` |

### D.2 依赖项清单

| 依赖 | 类型 | 用途 | 安装方式 | 必需性 |
|------|------|------|---------|--------|
| **cloudflared** | 外部二进制 | 建立 Cloudflare Tunnel | GitHub Releases 下载 | **可选**（仅公网访问需要） |
| Node.js >= 18 | 外部运行时 | trace-engine-web / trace-to-edm 服务 | nodejs.org | trace-engine-web & trace-to-edm 必需 |
| Python >= 3.10 | 外部运行时 | edm-takens-web 后端 | python.org | edm-takens-web 必需 |
| npm | 包管理 | 安装 Node 依赖 | 随 Node.js 分发 | Node 项目必需 |

### D.3 cloudflared 安装路径约定

脚本默认将 cloudflared 加入 PATH 的两个位置（任一即可）：
1. **系统 PATH**：通过 `where cloudflared` 检测
2. **`C:\Program Files (x86)\cloudflared\`**：脚本启动时会自动 append 到 PATH

下载地址：<https://github.com/cloudflare/cloudflared/releases/latest>

Windows x86_64 推荐 `cloudflared-windows-amd64.msi`（安装版）或 `cloudflared-windows-amd64.exe`（重命名为 `cloudflared.exe` 放入上述目录）。

### D.4 脚本统一行为契约

三个 `启动隧道.bat` 与 `启动隧道.ps1` 遵循以下统一契约（2026-07-20 修缮后）：

| 契约项 | 实现方式 |
|--------|---------|
| **UTF-8 控制台** | `chcp 65001 >nul`（bat）/ `[Console]::OutputEncoding = UTF8`（ps1） |
| **cloudflared 预检** | `where cloudflared >nul 2>nul`，缺失则提示安装链接并退出 |
| **运行时预检** | `where node` / `where python`，缺失则提示并退出 |
| **npm 依赖自愈** | 检测 `node_modules` 缺失时自动 `npm install` |
| **相对路径** | `cd /d "%~dp0"`（bat）/ `Split-Path -Parent $MyInvocation...`（ps1），便携式兼容 |
| **后端独立窗口** | `start "标题" cmd /c "..."` 启动到新窗口，不阻塞隧道主流程 |
| **端口动态探测** | netstat / Get-NetTCPConnection 扫描端口范围，避免硬绑定 |
| **隧道关闭清理** | `taskkill /fi "WINDOWTITLE..."`（bat）/ `try/finally + Stop-Process`（ps1） |

### D.5 端口探测范围

| 项目 | 默认端口 | 探测范围 | 说明 |
|------|---------|---------|------|
| edm-takens-web | 5173 | 固定 | Vite 开发服务器默认端口，不探测 |
| trace-engine-web | 3000 | 3000~3020 | 与 `start.ps1` 的端口递增逻辑一致 |
| trace-to-edm | 3100 | 3100~3120 | 与 `server.js` 默认 PORT=3100 一致 |

### D.6 安全注意事项

1. **trycloudflare 域名为临时公网链接**，任何获得 URL 的人都可访问，请勿用于敏感数据。
2. 隧道关闭后，公网链接立即失效；下次启动会分配新域名。
3. 如需固定域名，需配置 Cloudflare 账号的 Named Tunnel（参见 `cloudflared tunnel login` 与 `cloudflared tunnel create`）。
4. 脚本不修改任何防火墙规则，仅通过 Cloudflare 边缘节点中转流量。
5. 公网访问会绕过 `localhost` CORS 限制，如需收紧 CORS，请通过环境变量配置：
   - `trace-engine-web`：`TRACE_CORS_ORIGIN=https://your-domain.trycloudflare.com`
   - `edm-takens-web`：`EDM_CORS_ORIGINS=https://your-domain.trycloudflare.com`
   - `trace-to-edm`：`TRACE_TO_EDM_CORS_ORIGINS=https://your-domain.trycloudflare.com`

### D.7 便携式目录同步

三个项目的隧道脚本已纳入同步白名单，`sync_all_portable.py` 执行后会同步到便携式目录：

```
Complement\
└── TRACE Engine(EDM-Takens CCM)\
    ├── edm-takens-web\
    │   ├── 启动隧道.bat          ← 同步
    │   └── 启动隧道.ps1          ← 同步
    ├── trace-engine-web\
    │   └── 启动隧道.bat          ← 同步
    └── trace-to-edm\
        ├── 启动隧道.bat          ← 同步
        └── 启动隧道.ps1          ← 同步
```

`sync_portable.py`（trace-to-edm 专用）的 `TOP_FILE_WHITELIST` 已显式包含 `启动隧道.bat` 与 `启动隧道.ps1`；`sync_product.py`（trace-engine-web）与 `sync_all_portable.py`（edm-takens-web）使用黑名单 `ignore_patterns`，隧道脚本不在排除列表中，自动同步。

### D.8 修缮记录（2026-07-20）

| 修复项 | 原问题 | 修复后 |
|--------|--------|--------|
| `chcp 65001` 缺失 | 中文路径在 cmd 中乱码 | 全部 bat 增加 `chcp 65001 >nul` |
| cloudflared 预检缺失 | 未安装时直接报错，提示不明 | 增加 `where cloudflared` 检测 + 安装链接 |
| `trace-to-edm/启动隧道.ps1` 硬编码路径 | `$root = "F:\攻略\..."` 在便携式目录失效 | 改用 `Split-Path -Parent $MyInvocation...` 相对路径 |
| 后端进程阻塞隧道 | `start /B` + `pause` 导致主流程阻塞 | 改用 `start "标题" cmd /c "..."` 独立窗口 + 端口探测 |
| 隧道关闭后子进程残留 | Ctrl+C 后后端窗口不关闭 | bat 增加 `taskkill /fi "WINDOWTITLE..."`，ps1 增加 `try/finally + Stop-Process` |
| npm 依赖缺失未自愈 | 首次运行直接报错 | 增加 `if not exist node_modules` 自动 `npm install` |
| 端口冲突未探测 | 固定端口被占用时隧道连不上 | 增加 netstat/Get-NetTCPConnection 动态探测 |

---

元审计 Q4 微服务API设计 (2026-07-20)
附录 D 外部依赖 cloudflared 陈述 (2026-07-20)
