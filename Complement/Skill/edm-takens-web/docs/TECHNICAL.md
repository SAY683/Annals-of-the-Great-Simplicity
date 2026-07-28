# EDM-Takens Web — 技术文档

## 1. 架构总览

```
┌─────────────────┐      HTTP /api/*      ┌─────────────────────────────┐
│   Vite 前端     │  ◄──────────────────►  │   Python/FastAPI 后端        │
│  (vanilla JS)   │   NDJSON streaming    │  ┌───────────────────────┐  │
└─────────────────┘   + status polling    │  │  api.py (routes)      │  │
                                          │  │  ├ /api/upload        │  │
                                          │  │  ├ /api/datasets/*    │  │
                                          │  │  ├ /api/analyze       │  │
                                          │  │  ├ /api/analyze/jobs  │  │
                                          │  │  ├ /api/analyze/jobs/{id}   │  │
                                          │  │  └ /api/analyze/jobs/{id}/stream │  │
                                          │  ├ /api/results/*     │  │
                                          │  ├ /api/history/*     │  │
                                          │  ├ /api/archives/*    │  │
                                          │  └───────────────────────┘  │
                                          │  ┌───────────────────────┐  │
                                          │  │  backend/edmtakens/   │  │
                                          │  │  复制的原 Skill src   │  │
                                          │  └───────────────────────┘  │
                                          └─────────────────────────────┘
```

设计目标：**不改动原 `edm-takens/` Skill**，把其核心算法封装为 Web 服务。

- 前端：Vite + 原生 JS，负责上传 CSV、选择列、展示实时日志与结果图。
- 后端：FastAPI，负责变量校验、调用 `run_full_analysis()`、流式返回日志。
- 算法层：从 `edm-takens/src/` 复制到 `backend/edmtakens/`，共有 4 处适应性修改（详见 `docs/ALGORITHM_AUDIT.md`），其中 `_paths.py` 支持运行时数据目录覆盖。

## 2. 目录结构

```
edm-takens-web/
├── backend/
│   ├── api.py              # FastAPI 入口（145行，仅路由挂载 + 向后兼容重导出）
│   ├── core/               # 核心基础设施
│   │   ├── locks.py        # 4 把并发锁（Semaphore/Lock）
│   │   └── runtime.py      # JobStore 工厂 + 运行时配置
│   ├── routes/             # API 路由（express.Router 模式）
│   │   ├── datasets.py     # 数据集管理（7 端点）
│   │   ├── analyze.py      # 分析执行（6 端点）
│   │   └── history.py      # 历史与归档（16 端点）
│   ├── services/           # 业务逻辑层
│   │   ├── file_management.py  # 文件管理 + CSV解析 + 路径安全
│   │   └── summary_builder.py  # 报告摘要生成
│   ├── workers/            # 后台任务
│   │   └── analysis_worker.py  # 分析任务执行器
│   ├── edmtakens/          # EDM 核心库（从 edm-takens/src/ 同步）
│   │   ├── _usability.py   # 可用性判定（统一入口）
│   │   ├── data_quality.py # 数据质量诊断
│   │   ├── edm_auditor.py  # 审计防火墙（6档verdict）
│   │   ├── pipeline.py     # 主流水线
│   │   ├── sovereign_havok.py # HAVOK 分析
│   │   ├── _numpy_edm.py   # EDM/CCM/Multiview 纯 numpy 实现
│   │   └── ...
│   ├── job_store.py        # JobStore ABC + SQLite/InMemory 实现
│   └── sync_check.py       # 副本一致性校验
├── frontend/
│   ├── index.html
│   ├── src/
│   │   ├── main.js            # 前端逻辑 + 流式读取
│   │   └── style.css          # 极客/终端风格样式
│   └── package.json
├── data/                      # 上传的 CSV
├── results/                   # 运行时生成的 PNG / JSON（按 task_id 分目录）
├── archive/                   # 历史任务 zip 归档
├── docs/TECHNICAL.md          # 本文档
├── start_mvp.py               # 一键启动前后端
├── run_backend.py             # 后端启动入口
├── verify_mvp.py              # 系统核验脚本
├── requirements.txt
└── README.md
```

## 3. 核心 API

### 3.0 API 端点总表（共 29 端点）

> 元审计 Q12+ 同步 (2026-07-25)：补齐 `/api/datasets`、`/api/datasets/{filename}/columns`、`/api/datasets/{filename}/recommend`、`/api/analyze/stream`、`/api/results/{image_path}`、`/api/history/{task_id}`、`/api/archives/{task_id}/preview`、`/api/history/{task_id}/export/md`、`/api/history/{task_id}/export/html` 等遗漏端点。

| # | 方法 | 端点 | 说明 | 路由文件 |
|---|------|------|------|----------|
| 1 | GET | `/api/health` | 健康检查（返回 status + 时间戳） | datasets.py |
| 2 | GET | `/api/datasets` | 列出已上传的 CSV 数据集 | datasets.py |
| 3 | POST | `/api/upload` | 上传 CSV 文件（multipart/form-data，≤50MB） | datasets.py |
| 4 | GET | `/api/datasets/{filename}/columns` | 列出列名、数值列、预览与推荐目标列 | datasets.py |
| 5 | GET | `/api/datasets/{filename}/recommend` | 自动分析强度推荐（light/medium/heavy） | datasets.py |
| 6 | GET | `/api/datasets/{filename}/quality` | 每列 EDM 就绪度诊断（缺失率/自相关/平稳性等） | datasets.py |
| 7 | GET | `/api/datasets/{filename}/embed_curve` | 嵌入维度曲线（E_values + rho_values + optimal_E） | datasets.py |
| 8 | POST | `/api/analyze` | 阻塞式分析（一次性返回 summary + 图片 + 日志） | analyze.py |
| 9 | GET | `/api/analyze/stream` | 流式分析（NDJSON，便捷端点，内部创建 Job） | analyze.py |
| 10 | POST | `/api/analyze/jobs` | 创建异步分析任务（返回 job_id） | analyze.py |
| 11 | GET | `/api/analyze/jobs/{job_id}` | 轮询任务状态与日志（limit_logs 限制日志条数） | analyze.py |
| 12 | GET | `/api/analyze/jobs/{job_id}/stream` | 流式日志（NDJSON：log/result/error 事件） | analyze.py |
| 13 | GET | `/api/results/{image_path:path}` | 获取结果图片（按 task_id 分目录） | analyze.py |
| 14 | GET | `/api/history` | 列出历史任务 | history.py |
| 15 | GET | `/api/history/{task_id}` | 单任务完整数据（config + params + images + summary） | history.py |
| 16 | POST | `/api/history/{task_id}/archive` | 打包任务为 zip 并移入 archive/ | history.py |
| 17 | GET | `/api/history/{task_id}/download` | 下载任务 zip | history.py |
| 18 | DELETE | `/api/history/{task_id}` | 删除任务目录及其归档 | history.py |
| 19 | POST | `/api/history/cleanup` | 按天数/总大小上限清理（支持 dry_run 预览） | history.py |
| 20 | POST | `/api/history/batch` | 批量归档/删除/下载 | history.py |
| 21 | POST | `/api/history/compare` | 两两任务对比 | history.py |
| 22 | GET | `/api/history/{task_id}/export/json` | 下载任务摘要 JSON | history.py |
| 23 | GET | `/api/history/{task_id}/export/csv` | 下载任务摘要 CSV | history.py |
| 24 | GET | `/api/history/{task_id}/export/md` | 导出人话版 Markdown 报告（浏览器直接展示） | history.py |
| 25 | GET | `/api/history/{task_id}/export/html` | 导出人话版报告 HTML（暗色主题） | history.py |
| 26 | GET | `/api/archives` | 列出归档 | history.py |
| 27 | POST | `/api/archives/{task_id}/restore` | 恢复归档到活跃历史 | history.py |
| 28 | GET | `/api/archives/{task_id}/preview` | 预览归档内容（临时解压，不删原 zip） | history.py |
| 29 | DELETE | `/api/archives/{task_id}` | 删除归档 zip | history.py |

> 注：`GET /` 与 `GET /{path:path}`（api.py 中的 SPA 静态托管回退）不计入 29 个 API 端点之列。

### 3.1 健康检查

```http
GET /api/health
```

返回 `{"status":"ok","time":"..."}`。

### 3.2 上传 CSV

```http
POST /api/upload
Content-Type: multipart/form-data

file: <CSV>
```

仅接受 `.csv` 后缀文件，保存到 `data/`。

### 3.3 阻塞式分析

```http
POST /api/analyze
Content-Type: application/x-www-form-urlencoded

filename=game_log.csv&target_col=result&auto_fix=true&q=3
```

等待整个 pipeline 跑完，一次性返回 summary、图片列表和完整日志。适合脚本调用。

### 3.4 异步任务（推荐前端使用）

网页版把每次分析作为一个独立 Job 管理，避免长分析阻塞请求：

#### 创建任务

```http
POST /api/analyze/jobs
Content-Type: application/x-www-form-urlencoded

filename=game_log.csv&target_col=result&auto_fix=true&q=3
```

返回：

```json
{"job_id":"job_1720781234_a1b2c3d4","status":"pending"}
```

#### 轮询任务状态

```http
GET /api/analyze/jobs/{job_id}?limit_logs=200
```

返回：

```json
{
  "job_id": "job_1720781234_a1b2c3d4",
  "status": "running",
  "created_at": 1720781234.56,
  "updated_at": 1720781234.89,
  "logs": ["Pipeline stage 1/3 started", "..."],
  "result": null,
  "error": null
}
```

`status` 取值：`pending` / `running` / `done` / `error`。

#### 流式日志

```http
GET /api/analyze/jobs/{job_id}/stream
```

返回 `application/x-ndjson`，每行一个 JSON 对象：

```json
{"type":"log","data":"Pipeline stage 1/3 started"}
{"type":"log","data":"HAVOK rank r=2 ..."}
{"type":"result","data":{"success":true,"summary":{...},"task_id":"...","images":[...]}}
```

发生错误时：

```json
{"type":"error","data":{"detail":"Analysis failed: ..."}}
```

#### 异步实现要点

- **JobStore 抽象接口**：`backend/job_store.py` 定义了 `JobStore` ABC，包含 `create()`、`get()`、`spawn()`、`events()` 四个方法。FastAPI 路由只依赖该接口。
- **默认实现**：默认使用 `PersistentJobStore`（SQLite，`jobs.sqlite`），支持 `JOBS_DB` 环境变量指定数据库路径，服务重启后仍可通过 `job_id` 查询已完成任务；若 SQLite 初始化失败则回退到 `InMemoryJobStore`（内存任务注册表，最多保留 50 条近期记录）。每个 Job 在独立后台线程中执行 `run_full_analysis()`。
- 用 `contextlib.redirect_stdout` + `contextlib.redirect_stderr` 把输出导入线程安全的 `queue.Queue`。
- FastAPI 通过 `asyncio.to_thread(queue.get)` 异步取日志，生成 NDJSON 流。
- 前端同时做两件事：
  1. 通过 `/api/analyze/jobs/{job_id}/stream` 实时接收日志；
  2. 每 2 秒调用 `/api/analyze/jobs/{job_id}` 轮询状态并更新状态徽章。
- 若日志流意外断开，前端仍可通过轮询拿到最终 `result` 或 `error`。

#### 迁移到 Celery/RQ

`JobStore` 接口已经预留了迁移点：

1. 实现 `CeleryJobStore`（或 `RQJobStore`）：
   - `create()`：向消息队列发送任务，返回任务 ID。
   - `get()`：从结果后端读取任务状态、日志、结果并反序列化为 `Job`。
   - `spawn()`：无需额外操作（Celery worker 已独立运行）。
   - `events()`：从 Redis pub/sub 或结果后端轮询日志事件。
2. 修改 `create_job_store()` 工厂函数返回新实现。
3. 将 `_job_worker()` 注册为 Celery/RQ 任务，worker 内部调用 `store.get(job_id)` 更新状态。

这样前端与 FastAPI 路由几乎无需改动。

### 3.5 结果图片隔离

原 Skill 把结果图写入固定的 `results/*.png`。Web 版在每次分析时：

1. 通过 `_ANALYSIS_LOCK`(Semaphore(2)) 限制并发分析数为2，`_STDOUT_LOCK` 串行化 stdout 重定向。
2. 分析完成后，把本次新生成的图片和配置 JSON 移入 `results/<task_id>/`。
3. `/api/results/{task_id}/{filename}` 返回对应的任务结果图。

前端收到 `task_id` 后，按 `api/results/<task_id>/<filename>` 加载图片。这样多次分析的结果可以并存，也避免了浏览器缓存混淆。

### 3.6 与原 Skill 的关系

- `backend/edmtakens/` 复制自 `edm-takens/src/`，共有 4 处适应性修改（详见 `docs/ALGORITHM_AUDIT.md`），仅以下文件与源不同：
  - `_paths.py`（路径适配）
  - `__init__.py`（包注释）
  - `enhanced_cross_validate.py`（数据路径适配）
  - `environment_check.py`（路径检查适配）
- `backend/api.py`、前端、启动脚本、文档均为网页版新增，未修改原 `edm-takens/` 目录。

### 3.7 数据质量诊断与嵌入维度曲线

上传 CSV 后，前端可在运行分析前先查看数据质量：

```http
GET /api/datasets/{filename}/quality?target_col=...&variables=...
```

返回每列的缺失比例、唯一值比例、标准差、lag-1 自相关、趋势分、平稳性（ADF 或稳健代理）、异常值（IQR+MAD）、样本量提示等，并给出 `usable_for_edm` 建议和 `suggested_action`。

嵌入维度曲线接口：

```http
GET /api/datasets/{filename}/embed_curve?target_col=...&max_e=8
```

返回 `E_values`、`rho_values`、`optimal_E`，前端据此绘制 `rho(E)` 曲线。

### 3.8 历史分析生命周期管理

每次分析完成后，结果被移入 `results/<task_id>/`。前端“历史分析”面板支持：

| 端点 | 说明 |
|------|------|
| `GET /api/history` | 列出历史任务 |
| `POST /api/history/{id}/archive` | 打包为 zip 并移入 `archive/` |
| `GET /api/history/{id}/download` | 下载任务 zip |
| `DELETE /api/history/{id}` | 删除任务目录及其归档 |
| `POST /api/history/cleanup?days=30&max_size_mb=...&dry_run=true` | 按天数/总大小上限清理 |
| `POST /api/history/batch` | 批量归档 / 删除 / 下载 |
| `POST /api/history/compare` | 两两任务对比 |
| `GET /api/history/{id}/export/json` | 下载任务摘要 JSON |
| `GET /api/history/{id}/export/csv` | 下载任务摘要 CSV |
| `GET /api/archives` | 列出归档 |
| `POST /api/archives/{id}/restore` | 恢复归档到活跃历史 |
| `DELETE /api/archives/{id}` | 删除归档 zip |

### 3.9 持久化 JobStore

`backend/job_store.py` 提供 `JobStore` 抽象接口：

- `InMemoryJobStore`：开发/回退使用，最多保留 50 条近期记录。
- `PersistentJobStore`（默认）：使用 SQLite 持久化任务状态、日志与结果；支持 `JOBS_DB` 环境变量指定数据库路径。服务重启后仍可通过 `job_id` 查询已完成任务。

## 4. 变量选择策略

后端在上传 CSV 后会做以下过滤，降低 EDM/HAVOK 对非动力学列的敏感报错：

1. 使用多编码回退（`utf-8-sig` / `gbk` / `latin1`）读取 CSV，避免上传文件因编码问题在分析阶段失败。
2. 仅保留 `pandas` 识别为数值类型的列。
3. 至少保留 2 个数值列。
4. 排除常见标识列：`game`, `id`, `index`, `time`, `date`, `timestamp`, `seq`，以及中文 `时序` / `时间` / `序号` / `编号` / `索引` / `日期`。
5. 排除时间/日历列：`hour`, `minute`, `second`, `month`, `weekday`, `day`。
6. 排除近常数列（标准差 `< 1e-12`）。
7. 默认目标列优先选择连续数值列；若数据以 0/1 指示变量为主（如宽表 `yinshen_wide`），系统会在质量面板给出数据集级提示，避免误将二值列当作目标列。
8. 若用户手动指定变量，仅保留数值列；留空则取候选变量前 6 个，并确保 `target_col` 在列表中。

数据质量面板会展示**全部数值列**的诊断，并用标签区分 `目标` / `已选` / `未选`，方便用户识别宽表中哪些列实际进入了分析。

## 5. 部署与运行

### 5.1 手动分步启动

```bash
# 后端
pip install -r requirements.txt
python run_backend.py          # http://localhost:8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

### 5.2 一键启动

```bash
python start_mvp.py
```

该脚本会：

1. 启动后端并探测 `127.0.0.1:8000`。
2. 启动前端并探测 `127.0.0.1:5173`。
3. 实时打印 `[BE]` / `[FE]` 子进程输出。
4. 按 `Ctrl+C` 一并终止两个进程。

### 5.3 生产部署建议

当前 MVP 使用 Vite 开发服务器，不建议直接暴露在公网。生产可：

1. 前端：`npm run build` 生成 `frontend/dist/`，用 Nginx 或 Caddy 托管静态文件。
2. 后端：用 `gunicorn` + `uvicorn.workers.UvicornWorker` 运行 `api:app`。
3. 反向代理统一入口，例如：

   ```nginx
   location /api/ { proxy_pass http://localhost:8000/api/; }
   location / { try_files $uri $uri/ /index.html; }
   ```

4. 上传文件大小限制、CORS 白名单（生产环境应收窄 `allow_origins`）、请求超时在面向多用户前需要补齐。后端已将 `Content-Disposition` 加入 CORS `expose_headers`，确保前端可读取导出文件名。
5. 任务队列：默认使用 SQLite `PersistentJobStore`；多 worker 部署时请替换为 Celery/RQ，接口形状保持一致。

## 6. 已知限制与优化方向

| 问题 | 说明 | 后续优化 |
|------|------|----------|
| 小样本 N<50 | EDM Simplex ρ 可能达到 1.000，属于方法学现象 | 滚动交叉验证、结果声明中加入样本量提示 |
| 宽表 / 二值指示变量 | EDM 假设变量处于度量空间，0/1 指示变量占主导的宽表（如 `yinshen_wide`）会触发数据集级提示，建议仅作探索或改用分类/特征工程 | 提供聚合指标、主成分或分类模式入口 |
| 任务队列持久化 | 默认使用 SQLite `PersistentJobStore`，重启后仍可查询已完成任务；多 worker 部署时请替换为 Celery/RQ，接口形状保持一致 | 已预留 `JobStore` 抽象接口 |
| 图片直接保存到 `results/` | 同名文件会被覆盖 | 已按任务 ID 分目录，前端通过 API 获取 |

## 7. 开发约定

- 数据路径使用相对路径或环境变量，不硬编码绝对路径。
- `results/` 由后端自动创建，运行时产物不纳入版本控制（见 `.gitignore`）。
- 新增功能优先在网页版副本实现，保持原 Skill 的可移植性不变。
