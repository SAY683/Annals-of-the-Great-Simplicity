# 部署、发布整洁性与便携目录维护

## 1. 便携目录结构

```text
Complement/
├── start_all.bat / start_all.ps1     # 统一启动脚本
├── tools/                            # 环境检查、浏览器回归、运行产物清理、发布打包
├── Docs/                             # 本文档集
└── TRACE Engine(EDM-Takens CCM)/
    ├── edm-takens/                   # EDM 核心库
    ├── edm-takens-web/               # EDM Web 服务
    ├── trace-engine/                 # TRACE 引擎
    ├── trace-engine-web/             # TRACE Web 服务
    ├── trace-to-edm/                 # TRACE → EDM 桥接服务
    ├── Models/                       # 本地模型资源（不入 Git）
    ├── verify_portable.py            # 便携目录独立运行审计
    └── sync_product.py               # 可选的跨目录打包镜像工具
```

## 2. 唯一代码源与同步边界

本仓库自身就是唯一可维护代码源，不再依赖仓库外的 `.skills` 或其他制作目录。

- `edm-takens/src/` 是 EDM 算法唯一真源。
- `edm-takens-web` 直接导入上述算法源，不再维护 `backend/edmtakens/` 副本。
- `trace-engine/`、`trace-engine-web/` 与 `trace-to-edm/` 都从当前仓库内的相对路径运行。
- `sync_product.py` 只用于显式构建另一个便携镜像目录，不是日常运行或升级前置步骤。
- 模型权重、`node_modules/`、任务历史、日志和缓存均属于分发附属物或运行时状态，不由代码同步脚本猜测覆盖。

便携审计：

```powershell
cd "Complement"
python "TRACE Engine(EDM-Takens CCM)\verify_portable.py"
```

审计覆盖目录完整性、运行时污染、引擎导入与健康检查、API 契约以及 EDM/TRACE 跨项目同步。

## 3. 发布前整洁策略

原则：**Git 跟踪文件定义发布物；运行状态不进入代码包。**

### 3.1 查看并清理运行残留

```powershell
cd "Complement"
powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean_runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean_runtime.ps1 -Apply
```

默认只处理日志、缓存、临时脚本与过期隧道状态，不删除任务历史。确认确实要清理本机任务历史时：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean_runtime.ps1 -Apply -IncludeTaskHistory
```

`-IncludeTaskHistory` 会清理 `results/`、`archive/`、`work/`、`jobs.sqlite`、trace-to-edm 项目脚手架和测试任务数据。执行前应先做好需要的备份。

### 3.1.1 新闻 HTML 批量预处理

公开新闻 HTML 可在本地并行清洗，不依赖网络：

```powershell
python -m pip install -r tools\requirements-news.txt
python tools\prepare_news_corpus.py --html-dir news\html --out-dir news\normalized --workers 4
# 可选：预计算 Qwen 语义嵌入，避免重复批处理时再次运行模型
$env:TRACE_EMBEDDING_CACHE_DIR = "$env:TEMP\semantic-news"
python tools\warm_semantic_cache.py --corpus-dir news\normalized
python "TRACE Engine(EDM-Takens CCM)\smoke_e2e.py" --corpus-dir news\normalized --timeout-min 30
```

新闻正文默认保存在被 Git 忽略的本地目录；发布包只包含处理工具与论文元数据。

### 3.2 构建干净源码包

```powershell
cd "Complement"
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_release.ps1
```

脚本要求工作树干净，并先运行 Markdown 相对链接检查与 `verify_portable.py --no-e2e`，随后使用：

```text
git archive HEAD
```

生成 `release/Annals-of-the-Great-Simplicity-<commit>.zip` 和对应的 SHA256 manifest。脚本会拒绝缺少必需文件或包含运行状态/密钥的 ZIP。由于只打包 Git 跟踪文件，以下内容不会进入源码包：

- `node_modules/`
- `results/`、`archive/`、`work/`
- `jobs.sqlite`、日志、缓存、PID、隧道 URL
- 本地模型权重

模型权重继续作为独立 artifact 分发；Node 依赖通过 lockfile + `npm ci` 重建，Python 依赖通过 `requirements*.txt` 重建。
GraphRAG 的 `llama-server` 与 bge-m3 GGUF 属于外部运行时依赖。机器相关路径放在被 Git
忽略的 `Complement/GraphRAG-神纪图谱/scripts/local-paths.ps1`（从 `local-paths.example.ps1`
复制），不写死进脚本，也不会进入发布包。

### 3.3 发布前检查

```powershell
git status --short
git diff --check
python tools\check_env.py
python "TRACE Engine(EDM-Takens CCM)\verify_portable.py" --no-e2e
```

要求：工作树干净、文档相对链接 0 失效、便携审计 0 FAIL、发布 ZIP 的 prohibited-entry 检查为 0，且 manifest 的 SHA256 与 ZIP 一致。

## 4. Cloudflare 隧道

每个 Web 服务都有独立隧道脚本：

```text
trace-engine-web/
├── 启动隧道.bat
└── tunnel.ps1

trace-to-edm/
├── 启动隧道.bat
└── tunnel.ps1

edm-takens-web/
├── 启动隧道.bat
└── tunnel.ps1
```

统一入口：

```powershell
.\start_all.bat          # 默认仅本地 127.0.0.1
.\start_all.bat tunnel   # 启动本地 token 网关与 Cloudflare 隧道
```

隧道模式要求在本地网关上配置 `TUNNEL_ACCESS_TOKEN`。公开 URL 本身不构成鉴权。

## 5. 默认端口

| 服务 | 默认端口 | 备注 |
|---|---:|---|
| trace-engine-web | 3000 | 冲突时可在 3000-3020 间回退 |
| trace-to-edm | 3100 | Node.js 桥接服务 |
| edm-takens-web backend | 8000 | FastAPI |
| edm-takens-web frontend (Vite) | 5173 | 开发/便携启动 |
| GraphRAG LLM proxy | 15721 | 按本地代理配置启用 |
| GraphRAG embedding | 8081 | bge-m3/llama-server |

启动前检查端口：

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 3000,3100,5173,8000,8081,15721 }
```

## 6. 关键环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `TRACE_WORK_DIR` | TRACE 工作/输出目录 | 脚本目录 |
| `TRACE_ENGINE_SKILL_DIR` | 引擎 Skill 路径 | 自动探测 |
| `TRACE_PYTHON_CMD` | TRACE Python 解释器 | 自动探测 |
| `EDM_PYTHON_CMD` | EDM Python 解释器 | 自动探测 |
| `GRAPHRAG_PYTHON` | GraphRAG Python 解释器 | 自动探测 |
| `TRACE_TO_EDM_PORT` | trace-to-edm 起始端口 | `3100` |
| `EDMTAKENS_DATA_DIR` | EDM 数据目录 | 自动探测 |
| `JOBS_DB` | EDM 任务数据库路径 | `jobs.sqlite` |
| `EDM_TRUST_PROXY` | 设为 `1` 才信任转发头 | `0` |
| `TUNNEL_ACCESS_TOKEN` | 隧道网关访问令牌 | 启动时生成 |
| `GRAPHRAG_JSON_MODE` | GraphRAG JSON mode 能力覆盖 | `auto` |
| `COMPLEMENT_PYTHON_CANDIDATES` | 额外 Python 候选（分号分隔） | 空 |
| `TRACE_USE_WORKER` | 启用 batch TRACE 常驻 worker | `1` |
| `TRACE_CACHE_DIR` | TRACE result.json 内容缓存目录 | `work/cache/trace` |
| `TRACE_CACHE_DISABLE` | 设为 `1` 禁用 TRACE 缓存 | `0` |
| `TRACE_CACHE_VERSION` | TRACE 缓存键版本；算法或结果格式变更时递增 | `v1` |
| `TRACE_PREFETCH_WORKERS` | 批量文本 L1 预取并发数 | `2` |
| `EDM_CACHE_DIR` | batch EDM 结果缓存目录 | `work/cache/edm` |
| `EDM_CACHE_DISABLE` | 设为 `1` 禁用 EDM 缓存 | `0` |
| `EDM_CACHE_VERSION` | EDM 缓存键版本；分析实现变更时递增 | `v1` |
| `TRACE_EMBEDDING_CACHE_DIR` | Qwen 文本嵌入缓存目录；跨 E2E 复用时建议显式指定 | 项目 cache/embeddings |
| `TRACE_EMBEDDING_CACHE_DISABLE` | 设为 `1` 禁用语义嵌入缓存 | `0` |
| `TRACE_EMBEDDING_CACHE_VERSION` | 语义嵌入缓存键版本 | `v1` |
| `QWEN_DEVICE` | Qwen 推理设备：`auto` / `cuda` / `cpu`；显存紧张时建议 `cpu` | `auto` |
| `QWEN_LOAD_IN_4BIT` | CUDA 4-bit 量化：`auto` / `1` / `0` | `auto` |

## 7. 维护清单

### 日常维护

- [ ] 运行 `verify_portable.py`
- [ ] 确认无遗留服务进程占用 3000/3100/5173/8000
- [ ] 需要转发或公开访问时，先确认隧道网关和 token

### 代码修改后

- [ ] 运行相关单元测试与 `browser_smoke.py`
- [ ] 运行 `git diff --check`
- [ ] 运行 `verify_portable.py --no-e2e`
- [ ] 更新受影响的 Docs 与验收记录

### 发布前

- [ ] `git status --short` 为空
- [ ] `clean_runtime.ps1` 无意外运行残留
- [ ] `build_release.ps1` 成功并记录 SHA256
- [ ] 模型权重作为独立 artifact 校验，不混入源码包

### 模型更新

- [ ] 新模型放入 `Models/`，保留对应配置与 LICENSE
- [ ] 需要镜像到 `trace-engine/Models/` 时显式执行同步
- [ ] 更新 `presets.yaml`、`Docs/10-models.md` 与模型 SHA256 信息
