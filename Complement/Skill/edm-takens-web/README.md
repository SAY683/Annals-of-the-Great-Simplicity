# EDM-Takens Web (MVP)

Node.js/Vite 前端 + Python/FastAPI 后端的 EDM-Takens 网页版 MVP。

## 结构

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
│   │   └── history.py      # 历史与归档（12 端点）
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
├── data/                   # 上传的 CSV 存放处
├── results/                # 运行时生成的图片/配置（按 task_id 分目录）
├── archive/                # 历史任务 zip 归档
├── frontend/               # Vite + vanilla JS 前端
│   ├── index.html
│   ├── src/
│   │   ├── main.js         # 前端逻辑 + NDJSON 流式日志
│   │   └── style.css       # 极客/终端风格样式
│   └── package.json
├── docs/
│   └── TECHNICAL.md        # 技术文档
├── start_mvp.py            # 一键启动前后端
├── run_backend.py          # 后端启动入口
├── verify_mvp.py           # 系统核验脚本
└── requirements.txt
```

## 运行

### 方式一：一键启动（推荐）

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
python start_mvp.py
```

脚本会同时启动后端（`localhost:8000`）和前端（`localhost:5173`），按 `Ctrl+C` 一起停止。

### 方式二：分步启动

```bash
# 终端 1：后端
pip install -r requirements.txt
python run_backend.py

# 终端 2：前端
cd frontend
npm install
npm run dev
```

前端开发服务器 `http://localhost:5173` 会把 `/api/*` 代理到后端。

打开浏览器访问 `http://localhost:5173`。

## 快速验证（不打开浏览器）

后端启动后，可用 `curl` / PowerShell 直接验证分析链路：

```bash
curl -X POST http://localhost:8000/api/analyze \
  -d "filename=game_log.csv" \
  -d "target_col=result" \
  -d "auto_fix=true" \
  -d "q=3"
```

成功时返回 JSON：`success: true`，`interpretation: ok`，并列出 `images`。

### 异步任务 API（脚本/外部系统调用）

前端当前使用异步任务接口，脚本也可直接调用：

```bash
# 1. 创建任务
curl -X POST http://localhost:8000/api/analyze/jobs \
  -d "filename=game_log.csv" \
  -d "target_col=result" \
  -d "auto_fix=true" \
  -d "q=3"
# {"job_id":"job_...","status":"pending"}

# 2. 流式日志（NDJSON）
curl http://localhost:8000/api/analyze/jobs/{job_id}/stream

# 3. 轮询状态
 curl http://localhost:8000/api/analyze/jobs/{job_id}
```

## 使用

1. 上传 CSV（至少包含两列数值列）；支持 utf-8/gbk/latin1 等多种编码自动识别。
2. 选择目标列 `target_col`；后端会自动推荐一个非 ID、非二值的连续数值列。
3. 可指定分析变量（逗号分隔），留空自动选择有效数值列（最多 6 个）。
4. 在“数据质量预览”查看**全部数值列**的缺失率、唯一值、标准差、lag-1 自相关、趋势分、平稳性、异常值等诊断；标签区分 `目标` / `已选` / `未选`。点击“查看嵌入维度曲线”可预览 `rho(E)` 曲线。
5. 点击“运行分析”。
6. 页面右侧**实时日志终端**会显示 `job_id`、滚动输出后端分析过程，并每 2 秒轮询任务状态；完成后展示 HAVOK 诊断、稳定性层级、显著 CCM 因果对和结果图片。
7. 在“历史分析”可对已完成任务进行下载 zip、归档、删除、批量操作或两两对比；JSON / CSV 导出通过浏览器 `download` 机制触发文件保存。在“归档管理”可查看/恢复/删除归档。

### 变量自动过滤

为减少 EDM/HAVOK 对非动力学列的敏感报错，后端会自动排除以下列：

- 明显标识列：`game`, `id`, `index`, `time`, `date`, `timestamp`, `seq` 等
- 时间/日历列：`hour`, `minute`, `second`, `month`, `weekday`, `day`
- 近常数列（标准差 `< 1e-12`）

### 结果隔离

每次分析会生成唯一的 `task_id`，结果图片和配置 JSON 被移动到 `results/<task_id>/`。前端展示的图片 URL 也包含该 `task_id`，因此多次运行不会互相覆盖，也便于追踪历史结果。

## 常见问题

### 前端端口被占用

Vite 默认使用 5173；若被占用会自动换到 5174/5175 等。以终端实际输出为准，例如：

```
Local: http://localhost:5174/
```

### 后端端口 8000 被占用

结束占用 8000 的 Python 进程，或临时修改 `run_backend.py` 中的 `port`。

### `Need at least 2 numeric columns`

CSV 中数值列不足。确保除目标列外还有至少一个数值变量。

### `Interpretation: error: Encountered all NA values`

通常是某些列（如时间戳 `hour`）导致单变量分析失败。已在上传后的变量选择中自动排除；如仍出现，可在“分析变量”里手动剔除可疑列。

### 宽表（很多列）识别不理想

EDM 要求变量处于度量空间。若 CSV 中大部分是 0/1 指示变量（如 `yinshen_wide`），系统会在“数据质量预览”顶部提示“数值列中 X/Y 为二值/指示变量”。此时建议：

- 手动指定一个连续指标作为 `target_col`；
- 或仅把宽表当作探索性分析，结果解读需格外谨慎。

### JSON / CSV 导出无法下载或显示为文本

后端接口已设置 `Content-Disposition: attachment`，且 CORS 暴露了该响应头。前端使用 Blob + `<a download>` 触发保存。若仍遇到浏览器直接显示文本，请检查：

- 是否通过前端“历史分析”面板中的 JSON / CSV 按钮触发；
- 浏览器插件是否拦截了下载；
- 生产部署时是否在反向代理中透传了 `Content-Disposition` 头。

## 环境要求

- Python 3.10+（测试于 3.13）
- Node.js 18+（测试于 22）
- 推荐安装 `pyEDM`，否则部分功能会回退到纯 numpy 实现

### 历史分析与归档 API

| 操作 | 方法 | 端点 | 说明 |
|------|------|------|------|
| 历史列表 | GET | `/api/history` | 列出 `results/` 下的任务 |
| 归档 | POST | `/api/history/{task_id}/archive` | 打包为 zip 并移入 `archive/` |
| 下载 | GET | `/api/history/{task_id}/download` | 下载任务 zip |
| 删除 | DELETE | `/api/history/{task_id}` | 删除任务目录及其归档 |
| 清理 | POST | `/api/history/cleanup?days=30&dry_run=true` | 按天数/大小清理旧数据 |
| 批量 | POST | `/api/history/batch` | `{"action":"archive|delete|download","task_ids":[...]}` |
| 对比 | POST | `/api/history/compare` | `{"task_ids":[id1,id2]}` |
| 导出 JSON | GET | `/api/history/{task_id}/export/json` | 下载任务摘要 JSON |
| 导出 CSV | GET | `/api/history/{task_id}/export/csv` | 下载任务摘要 CSV |
| 归档列表 | GET | `/api/archives` | 列出 `archive/` 下的 zip |
| 恢复归档 | POST | `/api/archives/{task_id}/restore` | 解压归档回 `results/` |
| 删除归档 | DELETE | `/api/archives/{task_id}` | 删除归档 zip |

## 与原 Skill 的关系

- `backend/edmtakens/` 是从 `edm-takens/src/` 复制而来。
- Web 版对 `backend/edmtakens/` 共有 4 处适应性修改（详见 `docs/ALGORITHM_AUDIT.md`），仅以下文件与源不同：
  - `_paths.py`（路径适配）
  - `__init__.py`（包注释）
  - `enhanced_cross_validate.py`（数据路径适配）
  - `environment_check.py`（路径检查适配）
- `backend/api.py` 是网页版新增封装，未修改原 `edm-takens/` 目录下的任何文件。
