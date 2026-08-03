# Round 21 — 5 项目 HTTP API 路由审查矩阵

> 创建: 2026-07-27
> 范围: trace-engine-web / trace-to-edm / edm-takens-web (核心库无 HTTP 路由)
> 视角: PM + 算法工程师 + 安全审计
> 关联: ROUND21_ACTION_PLAN.md P0-A

---

## 0. 总体统计

| 项目 | 路由数 | 入参校验 | friendly error | 鉴权 | 日志 | P0 | P1 | P2 |
|------|--------|---------|---------------|------|------|----|----|-----|
| trace-engine-web | 25 | 11 (44%) | 9 (36%) | 21 (84%) | 5 (20%) | 1 | 5 | 5 |
| trace-to-edm | 32 | 13 (41%) | 6 (19%) | 31 (97%) | 1 (3%) | 3 | 7 | 6 |
| edm-takens-web | 30 | 17 (57%) | 22 (73%) | 0 (0%) | 0 (0%) | 3 | 5 | 5 |
| **合计** | **87** | **41 (47%)** | **37 (43%)** | **52 (60%)** | **6 (7%)** | **7** | **17** | **16** |

**核心结论**:
- **7 个 P0 安全漏洞** (1 个路径遍历 + 2 个未校验路径参数 + 1 个零鉴权 + 1 个错误泄漏 + 1 个无 schema)
- **日志覆盖率极低 (7%)** — 故障排查几乎不可能
- **错误响应格式碎片化** — 每项目至少 2-3 种不同结构
- **edm-takens-web 零鉴权零日志** — 完全裸奔

---

## 1. P0 严重问题清单 (立即修复)

### P0-1: trace-engine-web `POST /api/retry/:id` 路径遍历漏洞

- **位置**: routes/analysis.js:330-370 (第 341 行 `path.join(INPUTS_DIR, ${id}.txt)` + `fs.readFileSync`)
- **问题**: 未调用 `isValidId(id)` 校验,直接拼路径读文件
- **影响**: 攻击者可传 `id=../../etc/passwd` 读取任意文件
- **状态**: 🔴 待修复

### P0-2: trace-to-edm `DELETE /api/projects/:name` 任意目录删除

- **位置**: server.js:1397
- **问题**: name 直接传给 `pyCall(['--delete-project', name])`,无格式校验
- **影响**: 若 Python 端用 name 拼接路径删除,可删任意目录
- **状态**: 🔴 待修复

### P0-3: trace-to-edm `POST /api/projects` / `PUT /api/projects/activate` name 未校验

- **位置**: server.js:1372, 1384
- **问题**: name 必填检查但无格式校验,可含 `../` 等特殊字符
- **影响**: 项目切换到恶意 name 后,后续 CSV 读取可能走任意路径
- **状态**: 🔴 待修复

### P0-4: trace-to-edm `POST /api/edm/trigger` 入参完全无校验

- **位置**: server.js:862
- **问题**: target/q/time_start 等直接 String() 后塞进 spawn args
- **影响**: 恶意输入触发 Python 端异常或长时间运行
- **状态**: 🔴 待修复

### P0-5: edm-takens-web 全端点零鉴权

- **位置**: routes/datasets.py / analyze.py / history.py 全部
- **问题**: 无任何 Depends 鉴权依赖,DELETE/POST 破坏性操作完全开放
- **影响**: 任何能访问 API 端口的请求方可任意删除历史、上传任意 CSV
- **状态**: 🔴 待修复 (但本地开发环境可暂缓,生产部署前必须补)

### P0-6: edm-takens-web `POST /api/analyze` 泄露内部错误

- **位置**: routes/analyze.py:130 `raise HTTPException(500, detail=job.error)`
- **问题**: 直接把 worker 内部异常字符串回写客户端
- **影响**: 泄露文件路径、堆栈片段、库内部信息
- **状态**: 🔴 待修复

### P0-7: edm-takens-web `batch` / `compare` 无 Pydantic 模型

- **位置**: routes/history.py:366, 446
- **问题**: `body: dict = Body(...)` 仅运行时校验,无 schema 文档
- **影响**: 易被构造畸形 body 绕过
- **状态**: 🔴 待修复

---

## 2. P1 高危问题清单

### P1-1: trace-engine-web 鉴权 fail-open 设计

- `TRACE_API_KEY` 未设置时所有鉴权禁用 (含管理员路径)
- 生产环境环境变量丢失即裸奔
- 建议: 至少 ADMIN_PATHS 强制要求 TRACE_ADMIN_KEY,或改 fail-closed

### P1-2: trace-engine-web 错误响应格式碎片化

- 分析路由: `{success, error, code, field, traceId}`
- jobs 路由: `{success, error}` (无 code)
- models: `{error, detail}` (无 success)
- 500 错误多数缺 code 字段
- 建议: 统一为 `{success: false, error, code, traceId}`

### P1-3: trace-engine-web 管理员操作无审计日志

- `/api/admin/cleanup` / `/api/jobs/clear` / `DELETE /api/jobs/:id` / `POST /api/jobs/batch-delete` 均无 reqLog
- 高危操作无法通过 trace_id 追溯
- 建议: 这些路由添加 reqLog(req, 'info', ...) 调用

### P1-4: trace-to-edm 22/32 端点错误响应直接回 e.message

- `e.message` 可能泄漏内部文件路径、Python 异常堆栈片段
- 建议: 统一为通用 friendly message + 服务端日志记录 detail

### P1-5: trace-to-edm API Key 中间件 try/catch 降级

- `../shared/auth_middleware` 加载失败时仅 console.warn,全部 API 变 PUBLIC
- 生产部署若依赖该模块但文件丢失,无声息暴露所有接口
- 建议: 生产环境必须显式设置 CROSS_PROJECT_API_KEY,否则启动 fail-fast

### P1-6: edm-takens-web 全仓零日志

- 任何端点出错都无 logger.error/warning 记录,仅 print/traceback 到 stderr
- 生产环境无法做请求级审计、错误溯源、访问统计
- 建议: 配置 logging.getLogger("edm"),各端点 except 分支记录 logger.exception

### P1-7: edm-takens-web `GET /api/analyze/stream` 违反 REST 语义

- GET 方法带副作用 (创建 job 并写入 _JOB_STORE)
- 通过 Query 传 8 个业务参数 (含 intensity, project_name)
- 破坏 HTTP 缓存语义、CDN/网关幂等性假设
- 建议: 改为 POST,或拆分为"POST 创建 + GET 流式"两步

### P1-8: edm-takens-web `POST /api/archives/{task_id}/restore` 无 zip bomb 防护

- `shutil.unpack_archive` 无解压大小上限、无压缩比检查
- 恶意构造的 zip 可填满磁盘
- 建议: 解压前检查 zipfile.infolist() 总未压缩大小

### P1-9: trace-to-edm 单文件 1594 行无 Router 分离

- 路由与全局状态强耦合,无法独立单元测试
- 任何后续需求 (加鉴权分组、加 OpenAPI、加限流) 都将付出指数级成本
- 建议: 拆分为 8 个 Router 模块 (l0_system / l1_trajectory / ...)

---

## 3. P2 中危问题清单 (略)

详见各项目审查子报告。主要包括:
- trace-engine-web: 限流覆盖不全, code:'ERROR' 笼统值, /api/config 鉴权与注释不符
- trace-to-edm: 仅 1/32 端点显式 reqLog, SSE 错误无 HTTP 状态码, _pipelineRunning 进程内锁
- edm-takens-web: intensity 无 enum 校验, catch-all 风险, 数值参数无上界, export_task_md 185 行内联

---

## 4. 修复优先级与计划

### 立即修复 (Round 21 内)

| 编号 | 问题 | 修复复杂度 | 影响范围 |
|------|------|-----------|---------|
| P0-1 | trace-engine-web /api/retry/:id 路径遍历 | 1 行 | 单路由 |
| P0-2 | trace-to-edm DELETE /api/projects/:name | 3 行 | 单路由 |
| P0-3 | trace-to-edm POST/PUT /api/projects name 校验 | 6 行 | 2 路由 |
| P0-4 | trace-to-edm POST /api/edm/trigger 入参校验 | 10 行 | 单路由 |
| P0-6 | edm-takens-web POST /api/analyze 错误泄漏 | 3 行 | 单路由 |
| P0-7 | edm-takens-web batch/compare Pydantic 模型 | 20 行 | 2 路由 |

### 待规划 (Round 22+)

- P0-5: edm-takens-web 鉴权 (需设计 Depends 依赖链)
- P1-1~P1-9: 错误格式统一 / 日志覆盖 / Router 拆分 / REST 语义修复

---

## 5. 4 角色互审结论

### PM 视角
- 用户无法区分 4 种错误格式,前端需写多套兼容逻辑 → P1-2 优先
- 零鉴权导致任何访客可删历史 → P0-5 必须生产前修
- 日志缺失导致客服无法溯源用户问题 → P1-3/P1-6 优先

### 算法工程师视角
- 路径遍历是最低级安全漏洞 → P0-1 立即修
- trace-to-edm 单文件 1594 行影响所有后续维护 → P1-9 优先
- 错误响应直接回 e.message 影响调试 → P1-4 优先

### 数学家视角
- 路由审查与数学无关,但 /api/edm/trigger 入参无校验可能导致算法跑出预期范围 → P0-4 优先

### 统计家视角
- 错误响应碎片化导致前端难以统计错误率 → P1-2 优先
- 日志缺失导致无法做请求级错误分析 → P1-3/P1-6 优先
