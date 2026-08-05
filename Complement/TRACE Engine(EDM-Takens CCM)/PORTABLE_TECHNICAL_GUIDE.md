# TRACE Engine (EDM-Takens CCM) — 便携目录技术指南

> **版本**: 2026-08-03a (P1 修缮)
> **适用**: 本便携目录（`TRACE Engine(EDM-Takens CCM)/`）作为生产级独立部署单元
> **关联**: [README.md](README.md) · [verify_portable.py](verify_portable.py) · [sync_product.py](sync_product.py)

---

## 1. 便携目录契约

### 1.1 设计目标

本目录是 **自包含、开箱即用** 的便携式部署单元，满足以下生产级要求：

- **可移植**: 所有路径基于脚本自身位置推断，无硬编码绝对路径
- **可独立运行**: 不依赖外部开发目录即可启动全部 5 个子项目
- **可论证**: `verify_portable.py` 16 项契约 + `sync_check.py` 20 项一致性校验
- **可维修**: `sync_product.py` 支持自包含布局（脚本所在目录即成品根）

### 1.2 五大子项目

| 子项目 | 类型 | 默认端口 | 启动入口 |
|---|---|---|---|
| `trace-engine/` | Python 因果推断引擎 | — (CLI) | `examples/counterfactual_hybrid/run_cli.py` |
| `trace-engine-web/` | Node.js Web 服务 | 3000-3020 (自动探测) | `start.ps1` / `server.js` |
| `edm-takens/` | Python 科研算法库 (CLI) | — (CLI) | `run_pipeline.py` |
| `edm-takens-web/` | Python+JS Web 服务 | 后端 8000 / 前端 5173 | `start_mvp.py` |
| `trace-to-edm/` | Python+JS 桥接服务 | 3100 | `server.js` |

### 1.3 模型目录规范（严禁改动）

> ⚠️ **生产级约束**: 模型文件是训练产物，**严禁** 在便携目录维护过程中改动、删除或覆盖。

便携目录下存在 **两处** 模型目录，二者互为镜像（由 `sync_product.py:copy_models_to_engine()` 维护）：

| 路径 | 用途 | 引用方 |
|---|---|---|
| `Models/` (成品根) | 便携式布局探测信号 + SUPER 模式 | `trace-to-edm/config.py:_PORTABLE_MODELS_DIR` |
| `trace-engine/Models/` | 引擎内部 SUPER 模式加载 | `trace-engine/llama_worker.py` |

模型清单：
- `Qwen2.5-1.5B-Instruct/` — 便携式专属 Qwen 模型（trace-to-edm config.py 探测信号）
- `Qwen2.5-3B-Instruct/` — 便携式专属 Qwen 模型
- `shehui-llama/` — 默认 SUPER 模式（27M 参数 / ~108MB / max_position=256）
- `shenji-llama/` — 神学/史诗古文 SUPER 模式（469M / ~1.88GB / max_position=1024）
- `shehui-llama-v4-archive/` — 旧版归档（470M / ~1.88GB / max_position=1024）

**`sync_product.py` 行为**：仅当源与目标大小不一致时才覆盖，避免每次同步重写大文件（`sync_product.py:copy_models_to_engine`）。

---

## 2. 启动顺序与端口规划

### 2.1 推荐启动顺序

```
1. trace-engine-web   (port 3000)  ← 提交文本 → result.json
2. trace-to-edm       (port 3100)  ← 读取 result.json → 轨迹表 CSV
3. edm-takens-web     (port 8000)  ← 触发 EDM 分析 → 科研披露字段
```

数据流：
```
用户文本 → trace-engine-web → result.json → trace-to-edm → 轨迹表 CSV → edm-takens-web → EDM/CCM/HAVOK 分析
```

### 2.2 端口冲突排查

- 启动失败时先运行 `trace-engine-web/stop_servers.ps1` 清理 stale 进程
- `verify_portable.py:find_free_port()` 自动探测 3030-3050 空闲端口用于审计
- 用户可设置 `PORT` 环境变量强制指定端口

---

## 3. 便携目录验证契约（16 项）

`verify_portable.py` 执行 16 项独立运行审计（ROUND51 契约，含 E2E 全链路冒烟）：

| # | 检查项 | 文件位置 |
|---|---|---|
| 1 | 目录结构 | `check_structure` |
| 2 | **运行时产物污染**（含 edm-takens-web jobs.sqlite 防护） | `check_no_runtime_artifacts` |
| 3 | trace-engine 独立健康检查（`--quick` 模式） | `check_engine_health` |
| 4 | trace-engine 核心模块导入 | `check_engine_imports` |
| 5 | trace-engine 自检测试 | `check_engine_tests` |
| 6 | SUPER 模式导入路径（无 `presets.py` 遮蔽） | `check_super_worker_imports` |
| 7 | trace-engine-web 健康检查 + `/api/config` 契约 | `check_web_health` |
| 8 | trace-to-edm 轨迹表契约 | `check_trace_to_edm_contract` |
| 9 | 便携式代码修缮落地 | `check_portable_code_fixes` |
| 10 | Docs 同步 | `check_docs_sync` |
| 11 | EDM-TAKENS 项目同步完整性 | `check_skill_projects` |
| 12 | EDM-TAKENS CLI 模块导入（7 模块） | `check_edm_takens_cli` |
| 13 | EDM-TAKENS 科研披露字段（4 字段） | `check_edm_takens_disclosure_fields` |
| 14 | EDM-TAKENS 跨项目 sync_check | `check_edm_takens_sync_check` |
| 15 | BAT 编码合规（无中文 + `chcp 65001`） | `check_bat_encoding` |
| 16 | **E2E 全链路冒烟**（真实启动三服务，跑通 文本→TRACE→trace-to-edm→EDM） | `check_e2e_smoke` → `smoke_e2e.py` |

### 3.1 P1 修缮扩展：jobs.sqlite 污染防护

**病灶**: `edm-takens-web/backend/job_store.py:206` 默认将 `jobs.sqlite` 写入 `edm-takens-web/` 根目录。原版 `sync_product.py` 的 `edm_takens_web_ignore` 未排除该文件，导致：
1. 同步时 `jobs.sqlite` 被复制到便携目录
2. 携带旧任务历史与可能的敏感数据
3. 多次同步后便携目录累积陈旧数据库

**修复**（2026-08-03）：
- `sync_product.py:edm_takens_web_ignore` 新增 `jobs.sqlite`、`*.sqlite`、`*.sqlite-journal`、`*.sqlite-wal`、`*.sqlite-shm`、`*.db` 排除模式
- `verify_portable.py:check_no_runtime_artifacts` 扩展覆盖 `edm-takens-web/` 的 SQLite 污染检查

### 3.2 P1 修缮：health_check.py 超时治理

**病灶**: `verify_portable.py` 调用 `health_check.py` 时 60s 超时，因 `check_optional_deps()` 顺序导入 torch/transformers 耗时过长。

**修复**：
- `health_check.py:check_optional_deps(quick=True)` 跳过重依赖
- `verify_portable.py:check_engine_health` 改用 `--quick` 模式，超时放宽到 90s
- 并行导入（ThreadPoolExecutor），总耗时 ≈ max(单依赖) 而非 sum

---

## 4. sync_product.py 自包含布局

### 4.1 布局探测

`sync_product.py` 通过 `_SELF_CONTAINED` 标志探测布局类型（line 28）：

| 布局 | 触发条件 | 行为 |
|---|---|---|
| 自包含 | 脚本所在目录直接包含 `trace-engine/` 和 `trace-engine-web/` | 跳过这两项复制（避免 `src == dst`） |
| 开发 | 脚本在 `trace-engine-web/work/sync_product.py` | 从 `_WEB_ROOT.parent` 同步到 `product` |

### 4.2 关键文件保护白名单

`remove_old_root_after_migration()` 的 `keep_root` 白名单（line 216-222）：

```python
keep_root = {
    'verify_portable.py', 'sync_product.py', 'README.md',
    'PORTABLE_TECHNICAL_GUIDE.md',           # P1 修缮新增
    'test_mcp_protocol.py',                  # P1 修缮新增
    'test_cross_project_http.py',            # P1 修缮新增
}
```

**病灶历史**: 原版 `sync_product.py` 误删这三个文件，导致便携目录验证脚手架缺失。

### 4.3 EDM-TAKENS Web 排除模式

```python
edm_takens_web_ignore = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '*.pyo', '.git', '.gitignore',
    'node_modules', 'package-lock.json', 'work', 'outputs',
    'uploads', '*.log', 'data/uploads', '.pytest_cache',
    # P1 修缮: 运行时 SQLite 数据库防护
    'jobs.sqlite', '*.sqlite', '*.sqlite-journal',
    '*.sqlite-wal', '*.sqlite-shm', '*.db',
)
```

---

## 5. 跨项目协议契约

### 5.1 MCP 协议（JSON-RPC 2.0）

三个 Web 项目均暴露 `/mcp` 端点（21 个工具）：

| 项目 | 鉴权 | 工具数 |
|---|---|---|
| `trace-engine-web` | `middleware/auth.js` 保护 | 8 |
| `trace-to-edm` | `middleware/auth.js` 保护 | 7 |
| `edm-takens-web` | `Depends(require_auth)` 保护 | 6 |

**P1 修缮（2026-08-03）**: `edm-takens-web/backend/mcp.py` 的 `mcp_endpoint` 添加 `Depends(require_auth)`，并透传 `X-API-Key` / `Authorization` 头到内部 localhost 调用。

### 5.2 trace-to-edm 轨迹表契约

`bridge.py` 必须写入三列，`app.js` 的 `preferredCols` 必须包含这三列：

| 列名 | 含义 | 写入方 |
|---|---|---|
| `trace_status` | TRACE 引擎执行状态 | `bridge.py` |
| `trace_error` | TRACE 引擎错误信息 | `bridge.py` |
| `trace_mode` | 分析模式（LIGHT/DEEP/SUPER） | `bridge.py` |

`verify_portable.py:check_trace_to_edm_contract` 校验此契约。

### 5.3 EDM-TAKENS 跨项目同步

`edm-takens-web/backend/sync_check.py` 校验：
- `edm-takens/src/` 与 `edm-takens-web/backend/edmtakens/` 的 SHA256 一致性
- 4 个科研披露字段的存在性：
  - `is_strict_confirmatory`
  - `methodology_disclaimer`
  - `effective_lib_sizes`
  - `out_of_sample_used`

`edm-takens-web/backend/core/runtime.py:_auto_sync_check()` 在导入时自动执行（可用 `EDM_SKIP_SYNC_CHECK=1` 跳过）。

---

## 6. 测试脚手架

### 6.1 跨项目测试脚本

| 脚本 | 用途 | 触发方式 |
|---|---|---|
| `test_mcp_protocol.py` | MCP 端点协议一致性 | `python test_mcp_protocol.py` |
| `test_cross_project_http.py` | 跨项目 HTTP 契约 | `python test_cross_project_http.py` |
| `verify_portable.py` | 便携目录 14 项契约 | `python verify_portable.py` |
| `edm-takens-web/backend/sync_check.py` | 副本一致性 | `python sync_check.py` |

### 6.2 trace-engine 自检

```powershell
cd trace-engine
python tests/test_skill.py
python health_check.py --quick
```

`--quick` 模式跳过 torch/transformers/sentencepiece/causallearn 重依赖，仅检查核心 5 项（dowhy/numpy/pandas/sklearn/scipy），实测 ~10s。

---

## 7. 环境变量

| 变量 | 用途 | 默认值 |
|---|---|---|
| `PORT` | Web 服务端口 | 3000 (trace-engine-web) / 3100 (trace-to-edm) |
| `TRACE_WORK_DIR` | 工作/输出目录 | 脚本目录或 `%TEMP%\trace_verify_<port>` |
| `TRACE_ENGINE_SKILL_DIR` | 引擎 Skill 路径 | `<root>/trace-engine/examples/counterfactual_hybrid` |
| `TRACE_PYTHON_CMD` | Python 命令 | `python` |
| `TRACE_STAGE_TIMEOUT_MS` | SUPER 模式看门狗超时 | `900000` (15 分钟) |
| `TRACE_PRODUCT_DIR` | 成品目录（sync_product.py） | 自动探测便携布局 |
| `JOBS_DB` | EDM-TAKENS Web 任务数据库路径 | `edm-takens-web/jobs.sqlite` |
| `EDM_SKIP_SYNC_CHECK` | 跳过自动同步检查 | 未设置（执行） |
| `EDMTAKENS_DATA_DIR` | EDM-TAKENS Web 数据目录 | `edm-takens-web/data` |
| `QWEN_MODEL_PATH_1_5B` | Qwen 1.5B 模型路径 | 便携布局探测 |
| `QWEN_MODEL_PATH_3B` | Qwen 3B 模型路径 | 便携布局探测 |
| `SHEHUI_MODEL_PATH` | Shehui-LLaMA 模型路径 | 便携布局探测 |
| `SHENJI_MODEL_PATH` | Shenji-LLaMA 模型路径 | 便携布局探测 |

---

## 8. 故障排查

### 8.1 verify_portable.py 超时

- **症状**: `subprocess.TimeoutExpired: Command 'python health_check.py' timed out after 60 seconds`
- **根因**: `check_optional_deps()` 顺序导入 torch 耗时
- **修复**: 已切换 `--quick` 模式 + 90s 超时（P1 修缮）

### 8.2 SUPER 模式启动超时

- **症状**: SUPER 模式 120s 无响应
- **根因**: `trace-engine/presets.py`（旧版 v3）遮蔽 `examples/counterfactual_hybrid/presets.py`，导致 `llama_worker.py` ImportError
- **修复**: `sync_product.py:remove_legacy_engine_files()` 自动删除根级 `presets.py`
- **校验**: `verify_portable.py:check_super_worker_imports()` 检测遮蔽风险

### 8.3 长文本 500 错误

- **症状**: trace-to-edm 提交长文本（>2MB）返回 500
- **根因**: `server.js` 的 `express.json({limit: '2mb'})` 太小，sacred_texts/ 中文本可达 5MB+
- **修复**: 恢复 20mb 与 trace-engine-web 对齐（P1 修缮，`server.js:203-204`）

### 8.4 缓存戳不一致

- **症状**: 浏览器加载旧版 CSS/JS
- **根因**: 三大 Web 项目的 `index.html` 缓存戳不一致
- **修复**: 统一为 `20260803a`（P1 修缮）

### 8.5 jobs.sqlite 污染便携目录

- **症状**: 便携目录 `edm-takens-web/` 下出现 `jobs.sqlite` 携带旧任务
- **根因**: `sync_product.py` 的 ignore 模式未排除 SQLite 文件
- **修复**: `edm_takens_web_ignore` 新增 SQLite 排除（P1 修缮，`sync_product.py:111-117`）
- **校验**: `verify_portable.py:check_no_runtime_artifacts()` 扩展覆盖（P1 修缮）

### 8.6 端口残留

- 启动前运行 `trace-engine-web/stop_servers.ps1` 清理 stale 进程
- `edm-takens-web` 通过 `JOBS_DB` 环境变量重定向数据库位置
- `trace-to-edm` 的 `portable_verify.py` 提供独立验证

---

## 9. 与开发布局的差异

| 维度 | 开发布局 | 便携布局 |
|---|---|---|
| 脚本位置 | `.skills/trace-engine-web/work/sync_product.py` | 成品根 `sync_product.py` |
| EDM 源码 | `.skills/edm-takens/` 与 `.skills/edm-takens-web/` | 便携目录内 `edm-takens/` 与 `edm-takens-web/` |
| Qwen 模型 | `PROJECT_ROOT.parent.parent/Qwen2.5-X-Instruct/` | `Models/Qwen2.5-X-Instruct/` |
| 同步行为 | 全量复制 5 个项目 | 仅 EDM-TAKENS（trace-engine/web 跳过避免自我覆盖） |
| sync_check | 副本 vs 源 | 副本 vs 便携内副本（自洽） |

便携式布局探测信号（`trace-to-edm/config.py:36-40`）：

```python
_PORTABLE_MODELS_DIR = PROJECT_ROOT.parent / "Models"
_IS_PORTABLE_LAYOUT = (
    _PORTABLE_MODELS_DIR.exists()
    and (_PORTABLE_MODELS_DIR / "Qwen2.5-1.5B-Instruct").exists()
)
```

---

## 10. 维护日志

### 2026-08-03 (P1 修缮)

- 重建本指南（原版被 sync_product.py 误删，白名单保护为空保护）
- `sync_product.py:edm_takens_web_ignore` 新增 SQLite 排除
- `verify_portable.py:check_no_runtime_artifacts` 扩展覆盖 edm-takens-web
- `sync_product.py:remove_old_root_after_migration` 白名单保护本文件
- `health_check.py` 新增 `--quick` 模式 + 并行导入
- `trace-to-edm/server.js` body limit 恢复 20mb
- 三大 Web 项目 `index.html` 缓存戳统一为 `20260803a`
- `edm-takens-web/backend/mcp.py` 添加 `Depends(require_auth)` 鉴权

---

*本指南由 P1 修缮（2026-08-03）重建。所有引用路径与行号均来自实际代码，未经叙事化修饰。*
