# ROUND26 端到端 (E2E) 测试计划

> 覆盖三大 Web 项目 (trace-engine-web / trace-to-edm / edm-takens-web) 与两大 CLI 工具 (trace-engine CLI / edm-takens CLI) 的完整 E2E 测试矩阵。
> 文档版本: R26-1.0 · 生成日期: 2026-07-28 · 适用代码版本: trace-engine-web (26 routes) / trace-to-edm (33 routes) / edm-takens-web (FastAPI debt-19 拆分)

---

## 目录

- [第一部分: 测试环境准备](#第一部分-测试环境准备)
- [第二部分: 三大 Web 项目功能测试矩阵](#第二部分-三大-web-项目功能测试矩阵)
  - [2.1 trace-engine-web (端口 3000)](#21-trace-engine-web-端口-3000)
  - [2.2 trace-to-edm (端口 3100)](#22-trace-to-edm-端口-3100)
  - [2.3 edm-takens-web (前端 5173 / 后端 8000)](#23-edm-takens-web-前端-5173--后端-8000)
- [第三部分: CLI 工具测试矩阵](#第三部分-cli-工具测试矩阵)
- [第四部分: 跨项目集成测试](#第四部分-跨项目集成测试)
- [第五部分: 回归测试检查清单](#第五部分-回归测试检查清单)
- [附录 A: 验证脚本示例](#附录-a-验证脚本示例)
- [附录 B: 人工 vs 自动化标注](#附录-b-人工-vs-自动化标注)

---

## 第一部分: 测试环境准备

### 1.1 服务启动顺序 (依赖关系)

依赖链: `trace-engine-web (3000) → trace-to-edm (3100) → edm-takens-web (5173+8000)`

| 顺序 | 项目 | 启动命令 | 工作目录 | 端口 | 依赖 |
|------|------|----------|----------|------|------|
| 1 | trace-engine-web | `start.bat` 或 `node server.js` | `TRACE Engine(EDM-Takens CCM)\trace-engine-web\` | 3000 | Python (py_bridge.py) + Node.js + (可选) LLaMA Worker |
| 2 | trace-to-edm | `start.bat` 或 `node server.js` | `TRACE Engine(EDM-Takens CCM)\trace-to-edm\` | 3100 | Python (bridge.py) + 已运行的 trace-engine-web (轨迹上游) |
| 3a | edm-takens-web 后端 | `python run_backend.py` | `Skill\edm-takens-web\` | 8000 | Python (FastAPI + uvicorn) |
| 3b | edm-takens-web 前端 | `npm run dev` (开发) 或 `npm run build` (生产) | `Skill\edm-takens-web\frontend\` | 5173 (dev) / 8000 (prod 静态) | 后端 8000 已启动 |

启动验证 (健康检查 curl):
```bash
curl -s http://127.0.0.1:3000/api/health | jq .status      # 期望: "healthy" 或 "degraded"
curl -s http://127.0.0.1:3100/api/health                   # 期望: {"status":"ok",...}
curl -s http://127.0.0.1:8000/api/health                   # 期望: {"status":"ok",...}
```

环境变量约定 (可选, 用于鉴权/隧道):
- `TRACE_API_KEY` — trace-engine-web 鉴权 (未设置 = 开发模式)
- `CROSS_PROJECT_API_KEY` — trace-to-edm 跨项目鉴权
- `EDM_API_KEY` — edm-takens-web 鉴权
- `TRACE_HOST=0.0.0.0` — 允许外部访问 (默认 127.0.0.1)
- `TRACE_CORS_ORIGIN` — trace-to-edm CORS 白名单
- `EDM_CORS_ORIGINS` — edm-takens-web CORS 白名单
- `TRACE_PYTHON_CMD` — trace-to-edm 指定 Python 解释器

### 1.2 测试数据准备

| 数据类型 | 路径 | 用途 | 说明 |
|----------|------|------|------|
| 长文本 (中文) | `trace-engine-web\sample_input.txt` | TEW 文本分析输入 | 算法推荐/信息茧房主题, 单段约 600 字 |
| 短文本探针 | 内联 (≤200 字) | TEW GET `/api/analyze-stream` | 用于 P2-11 短文本探针路径 |
| CSV (文本+ts+source) | `trace-to-edm\data\inputs\news_40_csv_input.csv` | TTE Mode A 文本管线 | 40 条新闻, 列: timestamp,text,source |
| 轨迹 CSV (88 列) | `trace-to-edm\projects\default\narrative_meta_trajectories.csv` | TTE 轨迹查询/EDM 触发 | 由 trace-engine 生成, ≥15 行触发 EDM |
| EDM 数据集 | `edm-takens-web\data\game_log.csv` | ETW EDM 分析 | 默认数据集, target=result |
| EDM 备选数据 | `edm-takens-web\data\news_30_trajectories_cleaned.csv` | ETW 跨项目数据 | 30 条清洗后轨迹 |
| 八正道文本 | `trace-to-edm\sacred_texts\01_fuyin_祂志书.txt` 等 8 个 | TTE L3 投影 | 8 卷圣典对应 8 轴 |
| UUID 输入文本 | `trace-engine-web\work\inputs\{uuid}.txt` | TEW 任务重试 / TTE 回填 | 49 个历史 UUID |

测试夹具生成 (短/中/长三档):
- SHORT: "信息茧房加剧观点极化。" (12 字, 触发 P2-11 短文本探针)
- MEDIUM: sample_input.txt 前 200 字
- LONG: sample_input.txt 完整内容
- EMPTY: "" (空输入, 触发校验错误)
- INVALID: 纯标点 "。。。！" (触发概念提取失败)

### 1.3 浏览器与显示要求

| 项目 | 推荐浏览器 | 缩放测试矩阵 | 移动端断点 |
|------|-----------|--------------|-----------|
| trace-engine-web | Chrome ≥120 / Edge ≥120 | 75% / 100% / 125% / 150% | ≤900px (前端 main.css 响应式) |
| trace-to-edm | Chrome ≥120 / Edge ≥120 | 75% / 100% / 125% / 150% | ≤768px (override.css 媒体查询) |
| edm-takens-web | Chrome ≥120 / Edge ≥120 | 75% / 100% / 125% / 150% | ≤640px (人话版报告 @media) |

DevTools 设备模拟 (移动端):
- iPhone SE (375×667) — 验证 ≤900px 断点
- iPad Mini (768×1024) — 验证平板过渡
- Desktop 1920×1080 — 基准

SSE 兼容性: Chrome/Edge 原生支持 EventSource, 不需要 polyfill。

---

## 第二部分: 三大 Web 项目功能测试矩阵

### 2.1 trace-engine-web (端口 3000)

#### 基础设施测试 (TEW-INF)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEW-INF-001 | 健康检查 /api/health | 服务已启动 | `curl http://127.0.0.1:3000/api/health` | 200, JSON 含 `success:true`, `status` ∈ {healthy, degraded}, `skillReady`, `pythonReady`, `activeJobs`, `cacheSize` 字段 | curl + jq 断言 | ✅ 自动 |
| TEW-INF-002 | 配置加载 /api/config | TEW-INF-001 通过 | `curl http://127.0.0.1:3000/api/config` | 200, 含 `bridgeParamSchema` (非空对象), `superBridgeParamSchema`, `modes` 三键 (light/deep/super), `presets` 数组, `llamaModels.available` | curl + jq 校验 schema 非空 | ✅ 自动 |
| TEW-INF-003 | 版本端点 /api/version | 服务已启动 | `curl http://127.0.0.1:3000/api/version` | 200, 含 `BUILD_INFO`, `skillReady`, `pythonCmd` | curl | ✅ 自动 |
| TEW-INF-004 | Schema 端点 /api/schema | TEW-INF-002 通过 | `curl http://127.0.0.1:3000/api/schema` | 200, 含 `schema`, `superSchema`, `resultSchema`, `modes:['light','deep','super']`, `presets` | curl + jq | ✅ 自动 |
| TEW-INF-005 | 预设端点 /api/presets | 服务已启动 | `curl http://127.0.0.1:3000/api/presets` | 200, `presets` 对象含 default/standard/deep/archival/llama 等键 | curl | ✅ 自动 |
| TEW-INF-006 | 队列状态 /api/queue | 服务已启动 | `curl http://127.0.0.1:3000/api/queue` | 200, 含 `active`(数组), `queued`(数组), `maxConcurrent` | curl | ✅ 自动 |
| TEW-INF-007 | 指标端点 /api/metrics | 服务已启动 | `curl http://127.0.0.1:3000/api/metrics` | 200, 含 `statusCounts`, `uptimeSeconds`, `llamaWorkerReady` | curl | ✅ 自动 |
| TEW-INF-008 | 模型列表 /api/models | LLaMA 模型已下载 | `curl http://127.0.0.1:3000/api/models` (30s 超时) | 200, `models` 数组含 shehui-llama / shenji-llama, `count` ≥1 | curl | ✅ 自动 |
| TEW-INF-009 | 限流验证 | TEW-INF-001 通过 | 11 次连续 `curl -X POST /api/analyze-text` | 第 11 次返回 429, body 含 `RATE_LIMITED` code | curl 循环脚本 | ✅ 自动 |
| TEW-INF-010 | CORS 白名单 | 服务已启动 | `curl -H "Origin: http://evil.com" -I http://127.0.0.1:3000/api/health` | 响应无 `Access-Control-Allow-Origin: http://evil.com` | curl -I | ✅ 自动 |

#### LIGHT 模式端到端 (TEW-LIGHT)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEW-LIGHT-001 | 同步分析短文本 | TEW-INF-002 通过 | `POST /api/analyze-text` body `{"text":"信息茧房加剧观点极化。","mode":"light"}` | 200, `success:true`, `data.id` (UUID), `data.result` 含 ate/edge_count/ccm_coverage_pct=0 | curl + jq 断言 result.json | ✅ 自动 |
| TEW-LIGHT-002 | 同步分析长文本 | sample_input.txt | `POST /api/analyze-text` body `{"text":"<600字>","mode":"light"}` | 200, `result.ate` ≠ null, `edge_count` ≥0, `ccm_coverage_pct`=0 (LIGHT 不跑 CCM) | curl + jq | ✅ 自动 |
| TEW-LIGHT-003 | 缓存命中 | TEW-LIGHT-002 已执行 | 重复 `POST /api/analyze-text` 同 text+mode | 200, `cached:true`, `data.id` 与上次相同 | curl + jq | ✅ 自动 |
| TEW-LIGHT-004 | SSE 流式分析 | TEW-INF-002 通过 | `GET /api/analyze-stream?text=<200字>&mode=light` | Content-Type: text/event-stream, 收到 start → log → progress → done 事件, done 含 `code:0` | curl -N 流式读取 + grep event | ✅ 自动 |
| TEW-LIGHT-005 | SSE POST 别名 | TEW-LIGHT-004 通过 | `POST /api/analyze-stream` body `{"text":...,"mode":"light"}` | 同 TEW-LIGHT-004 | curl -N -X POST | ✅ 自动 |
| TEW-LIGHT-006 | 文件上传分析 | 准备 test.txt | `POST /api/analyze-file` multipart file=test.txt, mode=light | 200, `success:true`, 临时上传文件已删除 (检查 UPLOAD_DIR) | curl -F + ls UPLOAD_DIR | ✅ 自动 |
| TEW-LIGHT-007 | 文件类型拒绝 | 准备 test.csv | `POST /api/analyze-file` multipart file=test.csv | 400, error 含 "仅支持 .txt / .md" | curl -F | ✅ 自动 |
| TEW-LIGHT-008 | 结果获取 | TEW-LIGHT-001 完成 | `GET /api/result/{id}` | 200, JSON 含完整 result schema | curl + jq | ✅ 自动 |
| TEW-LIGHT-009 | 报告导出 (人话版) | TEW-LIGHT-001 完成 | `GET /api/report/{id}` | 200, Content-Type: text/markdown, 含 # 标题与因果结论 | curl + head | ✅ 自动 |
| TEW-LIGHT-010 | 任务重试 | 存在 status=error 的任务 | `POST /api/retry/{old_id}` | 200, `newId` (新 UUID), `data.result` 非空 | curl + jq | ✅ 自动 |
| TEW-LIGHT-011 | 重试非法 ID | - | `POST /api/retry/../../etc/passwd` | 400, `code:INVALID_ID` | curl | ✅ 自动 |
| TEW-LIGHT-012 | 取消运行中任务 | TEW-LIGHT-004 进行中 | `POST /api/cancel/{id}` | 200, `cancelled:true`, SSE 收到 error+done (code:125) | curl + SSE 监听 | ✅ 自动 |
| TEW-LIGHT-013 | 前端 UI 渲染 | 浏览器打开 http://127.0.0.1:3000 | 1. 打开页面 2. 选择 LIGHT 模式 3. 粘贴 sample_input.txt 4. 点击"开始分析" | 日志区实时滚动 SSE, 完成后展示结果卡片 (ate/edge_count), 出现"导出报告"按钮 | 浏览器截图 + DOM 检查 | ⚠️ 人工 |

#### DEEP 模式端到端 (TEW-DEEP)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEW-DEEP-001 | DEEP 同步分析 | TEW-INF-002 通过 | `POST /api/analyze-text` body `{"text":"<600字>","mode":"deep"}` | 200, `result.refuted_count` ≥0 (DEEP 跑反驳), `ccm_coverage_pct` >0 (DEEP 跑 CCM), `edge_stability_mean` 非空 | curl + jq | ✅ 自动 |
| TEW-DEEP-002 | 六战士诊断 SSE | TEW-DEEP-001 通过 | `GET /api/analyze-stream?text=<600字>&mode=deep` | SSE 日志含 "六战士"/"six_warriors" 阶段标记, 出现稳定性检查日志, done code:0 | curl -N + grep "六战士\|stability" | ✅ 自动 |
| TEW-DEEP-003 | 稳定性检查输出 | TEW-DEEP-001 完成 | `GET /api/result/{id}` 检查 `edge_stability_mean`, `permutation_p_value` | `permutation_p_value` ∈ [0,1], `edge_stability_mean` ∈ [0,1] | jq 断言 | ✅ 自动 |
| TEW-DEEP-004 | DEEP 概念图密度 | TEW-DEEP-001 完成 | 检查 `adj_density`, `condition_number` | `adj_density` >0, `condition_number` >0 | jq | ✅ 自动 |
| TEW-DEEP-005 | DEEP UI 阶段进度 | 浏览器 | 1. 选 DEEP 模式 2. 提交分析 3. 观察阶段卡片 | 出现 "六战士诊断" / "稳定性检查" 阶段卡片, 进度条推进 | 截图 | ⚠️ 人工 |

#### SUPER 模式端到端 (TEW-SUPER)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEW-SUPER-001 | SUPER 拒绝同步 | TEW-INF-002 通过 | `POST /api/analyze-text` body `{"text":...,"mode":"super"}` | 400, `code:SUPER_REQUIRES_STREAM` | curl | ✅ 自动 |
| TEW-SUPER-002 | SUPER SSE 流 | LLaMA Worker ready | `GET /api/analyze-stream?text=<600字>&mode=super` | SSE 含 `llama_progress` 事件, 出现速率预估 (tokens/s), done code:0 | curl -N + grep "tokens/s\|llama" | ✅ 自动 |
| TEW-SUPER-003 | SUPER 模型选择 | TEW-INF-008 通过 | `GET /api/analyze-stream?text=...&mode=super&config={"llama_model":"shehui-llama"}` | SSE 日志含 "shehui-llama" 加载信息 | curl -N | ✅ 自动 |
| TEW-SUPER-004 | SUPER 进度条 | 浏览器 | 1. 选 SUPER 2. 选模型 3. 提交 | 进度条 0→100%, 显示 tokens/s 速率, 预估剩余时间 | 截图 | ⚠️ 人工 |
| TEW-SUPER-005 | SUPER 取消 | TEW-SUPER-002 进行中 | `POST /api/cancel/{id}` | 200, `cancelled:true`, `reason:super_cancel_signal`, LLaMA Worker 状态 busy→false | curl + /api/metrics | ✅ 自动 |
| TEW-SUPER-006 | SUPER 队列等待 | 已有 SUPER 运行 | 提交第 2 个 SUPER 任务 | SSE 提示 "Worker busy, 排队中", 完成第 1 个后第 2 个自动开始 | curl -N 并发 | ⚠️ 人工 |
| TEW-SUPER-007 | SUPER 重试拒绝 | 存在 super 失败任务 | `POST /api/retry/{super_id}` | 400, `code:SUPER_RETRY_NOT_SUPPORTED` | curl | ✅ 自动 |

#### 历史记录管理 (TEW-HIST)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEW-HIST-001 | 任务历史列表 | 至少 1 个完成任务 | `GET /api/jobs` | 200, 数组含 id/mode/status/startTime/text | curl + jq | ✅ 自动 |
| TEW-HIST-002 | 单任务详情 | TEW-HIST-001 通过 | `GET /api/jobs/{id}` | 200, 含完整任务信息 | curl | ✅ 自动 |
| TEW-HIST-003 | 导出 JSON | TEW-HIST-001 通过 | `GET /api/jobs/export?format=json` | 200, Content-Type: application/json, 完整历史数组 | curl | ✅ 自动 |
| TEW-HIST-004 | 导出 CSV | TEW-HIST-001 通过 | `GET /api/jobs/export?format=csv` | 200, Content-Type: text/csv, 首行表头 | curl + head -1 | ✅ 自动 |
| TEW-HIST-005 | 清空历史 (管理员) | 设置 TRACE_API_KEY | `POST /api/jobs/clear` with API Key | 200, `success:true`, 后续 `GET /api/jobs` 返回空 | curl | ✅ 自动 |
| TEW-HIST-006 | 清空历史无权限 | 未设置 API Key | `POST /api/jobs/clear` | 403 | curl | ✅ 自动 |
| TEW-HIST-007 | TTL 清理触发 | 配置 outputTtlMs | `POST /api/admin/cleanup` with API Key | 200, 过期 outputs/ 目录已删除 | curl + ls outputs/ | ✅ 自动 |
| TEW-HIST-008 | 前端历史面板 | 浏览器 | 1. 点击"历史记录" 2. 查看列表 3. 点击详情 4. 勾选多个 5. 批量删除 6. 单个导出 | 列表渲染, 详情 modal, 批量删除确认, 导出下载 | 截图 + DOM | ⚠️ 人工 |

#### 错误处理 (TEW-ERR)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEW-ERR-001 | 空输入 | - | `POST /api/analyze-text` body `{"text":"","mode":"light"}` | 400, `code` 含 EMPTY_TEXT 或类似 | curl | ✅ 自动 |
| TEW-ERR-002 | 非法 mode | - | `POST /api/analyze-text` body `{"text":"x","mode":"invalid"}` | 400, `code:INVALID_MODE` | curl | ✅ 自动 |
| TEW-ERR-003 | 非法 config schema | - | `POST /api/analyze-text` body `{"text":"x","mode":"light","config":"{invalid}"}` | 400, `code` 含 CONFIG | curl | ✅ 自动 |
| TEW-ERR-004 | 并发超限 | 已有 maxConcurrentJobs 个任务 | 再提交 1 个 sync 分析 | 429, `code:TOO_MANY_CONCURRENT` | curl 并发 | ✅ 自动 |
| TEW-ERR-005 | 队列排队 | 已满并发 | 提交 SSE 流式 | SSE 提示 "已进入队列", 前面 N 个 | curl -N | ✅ 自动 |
| TEW-ERR-006 | 网络断开 (SSE) | TEW-LIGHT-004 进行中 | 浏览器 DevTools → Network → Offline | SSE 自动重连 (30s retry), 恢复后继续 | 浏览器观察 | ⚠️ 人工 |
| TEW-ERR-007 | 任务超时 | 配置 jobTimeoutMs 极小 | 提交长文本 SUPER | SSE error: timeout, done code:124 | curl + 配置 | ⚠️ 人工 |
| TEW-ERR-008 | Python 崩溃 | mock py_bridge 抛异常 | 提交分析 | SSE error 事件含 Python traceback | mock + curl | ✅ 自动 |
| TEW-ERR-009 | 非法 result ID | - | `GET /api/result/../../etc/passwd` | 400, `code:ERROR` (isValidId 拦截) | curl | ✅ 自动 |
| TEW-ERR-010 | 非法 report ID | - | `GET /api/report/..%2F..%2Fetc%2Fpasswd` | 400 | curl | ✅ 自动 |

#### 响应式布局 (TEW-RWD)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEW-RWD-001 | 75% 缩放 | 浏览器 | Ctrl+- 调至 75% | 布局不溢出, 文字可读, 按钮可点击 | 截图 | ⚠️ 人工 |
| TEW-RWD-002 | 100% 缩放 (基准) | 浏览器 | 默认 100% | 基准布局正常 | 截图 | ⚠️ 人工 |
| TEW-RWD-003 | 125% 缩放 | 浏览器 | Ctrl+= 调至 125% | 布局自适应, 无横向滚动 | 截图 | ⚠️ 人工 |
| TEW-RWD-004 | 150% 缩放 | 浏览器 | Ctrl+= 调至 150% | 关键控件可见, 表单可用 | 截图 | ⚠️ 人工 |
| TEW-RWD-005 | 移动端 ≤900px | DevTools iPhone SE | 375×667 | 响应式断点生效, 单列布局, 菜单折叠 | 截图 | ⚠️ 人工 |
| TEW-RWD-006 | 平板 768px | DevTools iPad Mini | 768×1024 | 过渡布局, 双列保留 | 截图 | ⚠️ 人工 |

### 2.2 trace-to-edm (端口 3100)

#### 基础设施测试 (TTE-INF)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-INF-001 | 健康检查 | 服务已启动 | `curl http://127.0.0.1:3100/api/health` | 200, `{"status":"ok","service":"trace-to-edm",...}` | curl | ✅ 自动 |
| TTE-INF-002 | 版本查询 | 服务已启动 | `curl http://127.0.0.1:3100/api/version` | 200, `version` 与 package.json 一致 | curl + jq | ✅ 自动 |
| TTE-INF-003 | 状态查询 | 轨迹 CSV 存在 | `curl http://127.0.0.1:3100/api/status` | 200, 含 `trajectory.rows`, `edm_ready` (≥15), `edm_targets` 数组, `layers.l1/l2/l3` | curl + jq | ✅ 自动 |
| TTE-INF-004 | 轨迹数据 | 轨迹 CSV 存在 | `curl http://127.0.0.1:3100/api/trajectory` | 200, `columns` 数组 (88 列), `rows` 数组, `total` | curl + jq | ✅ 自动 |
| TTE-INF-005 | 八正道正交性 | sacred_texts 已加载 | `curl http://127.0.0.1:3100/api/orthogonality` | 200, 含 Frobenius 距离矩阵 | curl (30s 超时) | ✅ 自动 |
| TTE-INF-006 | 项目列表 | 默认项目存在 | `curl http://127.0.0.1:3100/api/projects` | 200, 数组含 default 项目 | curl | ✅ 自动 |
| TTE-INF-007 | 模型列表 | - | `curl http://127.0.0.1:3100/api/models` | 200, `models` 含 qwen2.5-1.5b/3b, `active` | curl (30s) | ✅ 自动 |
| TTE-INF-008 | 输入 CSV 列表 | data/inputs 有文件 | `curl http://127.0.0.1:3100/api/inputs` | 200, `files` 数组含 news_40_csv_input.csv | curl | ✅ 自动 |
| TTE-INF-009 | 工作目录扫描 | work/inputs 有 UUID | `curl http://127.0.0.1:3100/api/work-scan` | 200, 含 UUID 列表 | curl | ✅ 自动 |
| TTE-INF-010 | CORS 隧道白名单 | tunnel_url.txt 存在 | `curl -H "Origin:https://xxx.trycloudflare.com" -I /api/health` | `Access-Control-Allow-Origin` 返回该域名 | curl -I | ✅ 自动 |
| TTE-INF-011 | 缓存 5s TTL | TTE-INF-003 通过 | 1s 内重复请求 /api/models | 响应时间 <100ms (命中缓存) | curl + time | ✅ 自动 |

#### LIGHT 模式端到端 (TTE-LIGHT)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-LIGHT-001 | 单文本管线 Mode A | 轨迹 CSV 可写 | `POST /api/run` body `{"text":"信息茧房加剧极化。","mode":"light","source":"test"}` | SSE 流, start → log → done, done 含 `trajectory_rows`+1, `edm_ready` | curl -N | ✅ 自动 |
| TTE-LIGHT-002 | CSV 批量管线 | news_40_csv_input.csv | `POST /api/run` body `{"csv_path":"data/inputs/news_40_csv_input.csv","mode":"light"}` | SSE 含 40 条处理日志, done `trajectory_rows` 增加 40 | curl -N | ✅ 自动 |
| TTE-LIGHT-003 | 路径遍历拒绝 | - | `POST /api/run` body `{"csv_path":"../../etc/passwd"}` | 400, `error: invalid path: traversal detected` | curl | ✅ 自动 |
| TTE-LIGHT-004 | 路径越界拒绝 | - | `POST /api/run` body `{"csv_path":"data/outputs/x.csv"}` | 400, `error: outside allowed input directories` | curl | ✅ 自动 |
| TTE-LIGHT-005 | 人话版报告导出 MD | 轨迹非空 | `GET /api/trajectory/export/md` | 200, `path` 指向 `projects/default/reports/latest.md` | curl + jq | ✅ 自动 |
| TTE-LIGHT-006 | 人话版报告查看 MD | TTE-LIGHT-005 通过 | `GET /api/trajectory/report` | 200, Content-Type: text/markdown, 含 88 列含义表 + 趋势 | curl + head | ✅ 自动 |
| TTE-LIGHT-007 | 人话版报告 HTML | TTE-LIGHT-005 通过 | `GET /api/trajectory/report?format=html` | 200, Content-Type: text/html, 含 `<details>` 折叠卡片 | curl + grep "<details" | ✅ 自动 |
| TTE-LIGHT-008 | 轨迹清空 | - | `POST /api/trajectory/clear` | 200, `rows:0`, CSV 仅保留 header | curl + jq | ✅ 自动 |

#### DEEP 模式端到端 (TTE-DEEP)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-DEEP-001 | DEEP 文本管线 | - | `POST /api/run` body `{"text":"<600字>","mode":"deep"}` | SSE done, 轨迹行 `ccm_coverage_pct` >0, `refuted_count` >0 | curl -N + jq trajectory | ✅ 自动 |
| TTE-DEEP-002 | 统一管线 deep | 数据集有 pending | `POST /api/pipeline/run` body `{"trace_mode":"deep"}` | SSE 含回填+文本两阶段, done `partial` 或 `success:true` | curl -N | ✅ 自动 |
| TTE-DEEP-003 | SUPER 模式拒绝 | - | `POST /api/pipeline/run` body `{"trace_mode":"super"}` | 回退为 light (traceMode 仅允许 light/deep), SSE 日志含 LIGHT | curl -N | ✅ 自动 |
| TTE-DEEP-004 | 管线防重入 | TTE-DEEP-002 进行中 | 再 `POST /api/pipeline/run` | SSE warn "管线正在运行中", done `success:false` | curl 并发 | ✅ 自动 |
| TTE-DEEP-005 | Partial 状态识别 | mock TRACE 部分失败 | `POST /api/pipeline/run` | SSE error 事件 (✖ TRACE), done `partial:true` | mock + curl | ✅ 自动 |

#### EDM 触发与轮询 (TTE-EDM)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-EDM-001 | EDM 触发 | 轨迹 ≥15 行, edm-takens-web 后端 8000 已启动 | `POST /api/edm/trigger` body `{"target":"ate","q":3}` | 200, `success:true`, 含 EDM 分析结果 | curl | ✅ 自动 |
| TTE-EDM-002 | EDM target 白名单 | - | `POST /api/edm/trigger` body `{"target":"evil_col"}` | 400, `code:INVALID_TARGET` | curl | ✅ 自动 |
| TTE-EDM-003 | EDM q 范围校验 | - | `POST /api/edm/trigger` body `{"q":1}` | 400, `code:INVALID_Q` | curl | ✅ 自动 |
| TTE-EDM-004 | EDM q 上限 | - | `POST /api/edm/trigger` body `{"q":21}` | 400, `code:INVALID_Q` | curl | ✅ 自动 |
| TTE-EDM-005 | EDM predict_window 校验 | - | `POST /api/edm/trigger` body `{"predict_window":-1}` | 400, `code:INVALID_PW` | curl | ✅ 自动 |
| TTE-EDM-006 | EDM 轮询代理 | 已提交 EDM job | `GET /api/edm/poll/{job_id}` | 200, 转发 edm-takens-web 的 job 状态 | curl | ✅ 自动 |
| TTE-EDM-007 | EDM 轮询后端不可达 | 停止 edm-takens-web | `GET /api/edm/poll/xxx` | 502, `error: edm-takens-web unreachable` | curl | ✅ 自动 |
| TTE-EDM-008 | EDM 轮询超时 | mock 8000 不响应 | `GET /api/edm/poll/xxx` | 504, `error: edm-takens-web timeout` | mock + curl | ✅ 自动 |

#### 回填 (Mode B) 测试 (TTE-REPLAY)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-REPLAY-001 | 全量回填 | work/inputs 有 UUID | `POST /api/replay` body `{"replay_all":true}` | SSE done, 轨迹行数增加 | curl -N | ✅ 自动 |
| TTE-REPLAY-002 | 指定 CSV 回填 | news_40_csv_input.csv | `POST /api/replay` body `{"csv_path":"data/inputs/news_40_csv_input.csv"}` | SSE done, 轨迹 +40 | curl -N | ✅ 自动 |
| TTE-REPLAY-003 | 选定 UUID 回填 | work-scan 有 UUID | `POST /api/replay-uuids` body `{"uuids":["<uuid1>","<uuid2>"]}` | SSE start 含 count, done success | curl -N | ✅ 自动 |
| TTE-REPLAY-004 | UUID 原文读取 | UUID 存在 | `GET /api/work-uuid/{uuid}/text` | 200, `text` 非空 | curl | ✅ 自动 |
| TTE-REPLAY-005 | UUID 非法字符 | - | `GET /api/work-uuid/../etc/text` | 400, `code:INVALID_UUID` | curl | ✅ 自动 |
| TTE-REPLAY-006 | 删除 UUID | UUID 存在 | `DELETE /api/work-uuid/{uuid}` | 200, 删除计数 | curl | ✅ 自动 |
| TTE-REPLAY-007 | 工作目录清理 (dry) | 存在孤儿 | `POST /api/work-clean` body `{"dry_run":true,"orphans_only":true}` | 200, dry_run 列表 | curl | ✅ 自动 |
| TTE-REPLAY-008 | 工作目录清理 (实删) | TTE-REPLAY-007 通过 | `POST /api/work-clean` body `{"dry_run":false}` | 200, 实际删除 | curl + ls | ✅ 自动 |

#### 数据集管理 (TTE-DS)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-DS-001 | 数据集查询 | - | `GET /api/dataset` | 200, `entries` 数组 + `summary` | curl | ✅ 自动 |
| TTE-DS-002 | 添加文本条目 | - | `POST /api/dataset/add-text` body `{"texts":[{"text":"x","source":"t"}]}` | 200, 计数增加 | curl | ✅ 自动 |
| TTE-DS-003 | 添加 UUID 条目 | - | `POST /api/dataset/add` body `{"uuids":["<uuid>"]}` | 200 | curl | ✅ 自动 |
| TTE-DS-004 | 删除条目 | 存在条目 | `POST /api/dataset/remove` body `{"id":"<id>"}` | 200, `success:true` | curl | ✅ 自动 |
| TTE-DS-005 | 清空已处理 | 存在 processed 条目 | `POST /api/dataset/clear-processed` | 200 | curl | ✅ 自动 |
| TTE-DS-006 | 重置 pending | - | `POST /api/dataset/reset` | 200, 全部 pending | curl | ✅ 自动 |
| TTE-DS-007 | 更新时间戳 | 存在条目 | `POST /api/dataset/update-ts` body `{"id":"<id>","timestamp":"2026-07-28"}` | 200 | curl | ✅ 自动 |

#### 项目管理 (TTE-PROJ)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-PROJ-001 | 创建项目 | - | `POST /api/projects` body `{"name":"test-proj"}` | 200, `success:true` | curl | ✅ 自动 |
| TTE-PROJ-002 | 项目名非法 (路径字符) | - | `POST /api/projects` body `{"name":"../evil"}` | 400, `code:INVALID_NAME` | curl | ✅ 自动 |
| TTE-PROJ-003 | 项目名非法 (空) | - | `POST /api/projects` body `{"name":""}` | 400 | curl | ✅ 自动 |
| TTE-PROJ-004 | 激活项目 | TTE-PROJ-001 通过 | `PUT /api/projects/activate` body `{"name":"test-proj"}` | 200, 后续 /api/status 项目名变更 | curl | ✅ 自动 |
| TTE-PROJ-005 | 删除项目 | TTE-PROJ-001 通过 | `DELETE /api/projects/test-proj` | 200 | curl | ✅ 自动 |
| TTE-PROJ-006 | 模型激活 (允许) | - | `POST /api/models/activate` body `{"model":"qwen2.5-1.5b"}` | 200, `active:qwen2.5-1.5b` | curl | ✅ 自动 |
| TTE-PROJ-007 | 模型激活 (拒绝 TRACE 模型) | - | `POST /api/models/activate` body `{"model":"shehui-llama"}` | 400, 提示用 trace-engine-web SUPER | curl | ✅ 自动 |

#### 跨项目导航与 BASE 组件 (TTE-NAV)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TTE-NAV-001 | BASE 组件切换 | 浏览器打开 3100 | 1. 检查顶部导航 2. 切换到 trace-engine-web 3. 切换回 | 导航链接正确 (3000/3100/5173), 主题一致 (tokusatsu.css) | 截图 + DOM href | ⚠️ 人工 |
| TTE-NAV-002 | 隧道模式适配 | tunnel_url.txt 存在 | 1. 启动隧道 2. 访问隧道 URL | CORS 放行 trycloudflare 域名, 前端 API 请求成功 | 浏览器 + curl | ⚠️ 人工 |
| TTE-NAV-003 | 共享主题同步 | shared/ 有更新 | 1. 修改 tokusatsu.css 2. 运行 sync_local_shared.py 3. 刷新 | 三个 Web 项目主题一致 | 视觉对比 | ⚠️ 人工 |

### 2.3 edm-takens-web (前端 5173 / 后端 8000)

#### 基础设施测试 (ETW-INF)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| ETW-INF-001 | 健康检查 | 后端已启动 | `curl http://127.0.0.1:8000/api/health` | 200, `{"status":"ok","time":...}` | curl | ✅ 自动 |
| ETW-INF-002 | 数据集列表 | data/ 有 CSV | `curl http://127.0.0.1:8000/api/datasets` | 200, `datasets` 数组含 game_log.csv | curl | ✅ 自动 |
| ETW-INF-003 | 前端开发重定向 | dist 不存在 | `curl http://127.0.0.1:8000/` | 302 → http://127.0.0.1:5173 | curl -I | ✅ 自动 |
| ETW-INF-004 | 前端 Vite 启动 | npm run dev | 访问 http://127.0.0.1:5173 | 200, HTML 含 `<div id="app">` | curl | ✅ 自动 |
| ETW-INF-005 | CORS 通配符拒绝 | - | `EDM_CORS_ORIGINS="*"` 启动 | 启动日志含 "SEC-01: 拒绝通配符" | 日志检查 | ✅ 自动 |
| ETW-INF-006 | CORS 凭证+通配符检测 | - | 配置 allow_credentials=true + origins=* | 被过滤, 不形成危险组合 | 日志检查 | ✅ 自动 |

#### 数据集与上传 (ETW-DS)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| ETW-DS-001 | 上传 CSV | 准备 test.csv | `POST /api/upload` multipart file=test.csv | 200, 文件存入 data/ | curl -F | ✅ 自动 |
| ETW-DS-002 | 上传非 CSV 拒绝 | 准备 test.txt | `POST /api/upload` multipart file=test.txt | 400, "Only CSV files" | curl -F | ✅ 自动 |
| ETW-DS-003 | 上传超大文件拒绝 | 准备 >50MB CSV | `POST /api/upload` | 413, "文件过大" | curl -F | ✅ 自动 |
| ETW-DS-004 | 上传二进制拒绝 | 文件首块含 NUL | `POST /api/upload` | 415 | curl -F | ✅ 自动 |
| ETW-DS-005 | 列列名 | game_log.csv | `GET /api/datasets/game_log.csv/columns` | 200, `columns` 数组 | curl | ✅ 自动 |
| ETW-DS-006 | 推荐 target | - | `GET /api/datasets/game_log.csv/recommend-target` | 200, 含推荐列名 | curl | ✅ 自动 |
| ETW-DS-007 | 数据质量评估 | - | `GET /api/datasets/game_log.csv/quality?target=result` | 200, 含 quality 指标 | curl | ✅ 自动 |
| ETW-DS-008 | 嵌入曲线 | - | `GET /api/datasets/game_log.csv/embed-curve?target=result` | 200, 含曲线数据 | curl | ✅ 自动 |
| ETW-DS-009 | 路径遍历拒绝 | - | `GET /api/datasets/..%2F..%2Fetc%2Fpasswd/columns` | 400, "Invalid filename" | curl | ✅ 自动 |

#### 分析任务 (ETW-ANALYZE)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| ETW-ANALYZE-001 | 异步任务提交 | game_log.csv 上传 | `POST /api/analyze/jobs` form: filename=game_log.csv, target_col=result, intensity=medium | 200, `job_id`, `status:pending/running`, `profile` | curl -F | ✅ 自动 |
| ETW-ANALYZE-002 | 任务状态轮询 | ETW-ANALYZE-001 通过 | `GET /api/analyze/jobs/{job_id}` | 200, 含 `status`, `logs`, `result` (完成后) | curl 轮询 | ✅ 自动 |
| ETW-ANALYZE-003 | 任务日志流 NDJSON | ETW-ANALYZE-001 通过 | `GET /api/analyze/jobs/{job_id}/stream` | Content-Type: application/x-ndjson, 每行一个 JSON | curl -N | ✅ 自动 |
| ETW-ANALYZE-004 | 同步阻塞分析 | - | `POST /api/analyze` form: filename=game_log.csv, target_col=result | 200, 完整 result (阻塞至完成) | curl -F (长超时) | ✅ 自动 |
| ETW-ANALYZE-005 | 阻塞端点并发限流 | 已有阻塞任务 | 再 `POST /api/analyze` | 429, 槽位满 | curl 并发 | ✅ 自动 |
| ETW-ANALYZE-006 | 任务不存在 | - | `GET /api/analyze/jobs/nonexistent` | 404, "Job not found" | curl | ✅ 自动 |
| ETW-ANALYZE-007 | 结果图片获取 | 任务完成有图 | `GET /api/analyze/jobs/{job_id}/images/{img}` | 200, image/png | curl | ✅ 自动 |
| ETW-ANALYZE-008 | auto_fix 参数 | - | `POST /api/analyze/jobs` auto_fix=false | 200, profile 反映 auto_fix 关闭 | curl -F | ✅ 自动 |
| ETW-ANALYZE-009 | 自定义 q/max_e | - | `POST /api/analyze/jobs` q=5, max_e=10 | 200, profile 含 q=5, max_e=10 | curl -F | ✅ 自动 |
| ETW-ANALYZE-010 | intensity 选项 | - | `POST /api/analyze/jobs` intensity=heavy | 200, profile=heavy | curl -F | ✅ 自动 |

#### 历史与归档 (ETW-HIST)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| ETW-HIST-001 | 历史列表 | 有完成任务 | `GET /api/history?limit=50` | 200, `tasks` 数组含 task_id/updated_at/images/has_config | curl | ✅ 自动 |
| ETW-HIST-002 | 历史详情 | 存在任务 | `GET /api/history/{task_id}` | 200, 含完整 config + summary | curl | ✅ 自动 |
| ETW-HIST-003 | 归档任务 | 存在任务 | `POST /api/history/{task_id}/archive` | 200, 任务移至 archives/ | curl + ls | ✅ 自动 |
| ETW-HIST-004 | 下载任务 ZIP | 存在任务 | `GET /api/history/{task_id}/download` | 200, application/zip | curl -o | ✅ 自动 |
| ETW-HIST-005 | 删除任务 | 存在任务 | `DELETE /api/history/{task_id}` | 200, results/{task_id} 已删除 | curl + ls | ✅ 自动 |
| ETW-HIST-006 | 清理历史 | - | `POST /api/history/cleanup` | 200, 清理计数 | curl | ✅ 自动 |
| ETW-HIST-007 | 归档列表 | 有归档 | `GET /api/archives` | 200, 归档数组 | curl | ✅ 自动 |
| ETW-HIST-008 | 恢复归档 | 有归档 | `POST /api/archives/{id}/restore` | 200, 任务回到 results/ | curl | ✅ 自动 |
| ETW-HIST-009 | 删除归档 | 有归档 | `DELETE /api/archives/{id}` | 200 | curl | ✅ 自动 |
| ETW-HIST-010 | 归档预览 | 有归档 | `GET /api/archives/{id}/preview` | 200, 含 summary | curl | ✅ 自动 |
| ETW-HIST-011 | 批量归档 | 多任务 | `POST /api/history/batch` body `{"action":"archive","task_ids":["id1","id2"]}` | 200, 批量结果 | curl | ✅ 自动 |
| ETW-HIST-012 | 批量删除 | 多任务 | `POST /api/history/batch` body `{"action":"delete","task_ids":[...]}` | 200 | curl | ✅ 自动 |
| ETW-HIST-013 | 批量下载 | 多任务 | `POST /api/history/batch` body `{"action":"download","task_ids":[...]}` | 200, ZIP | curl | ✅ 自动 |
| ETW-HIST-014 | 任务对比 | 2-8 个任务 | `POST /api/history/compare` body `{"task_ids":["id1","id2"]}` | 200, 对比结果 | curl | ✅ 自动 |
| ETW-HIST-015 | 对比少于 2 个 | - | `POST /api/history/compare` body `{"task_ids":["id1"]}` | 422 (Pydantic min_items=2) | curl | ✅ 自动 |
| ETW-HIST-016 | 对比超过 8 个 | - | `POST /api/history/compare` body 9 个 id | 422 (max_items=8) | curl | ✅ 自动 |
| ETW-HIST-017 | 导出 JSON | 存在任务 | `GET /api/history/{task_id}/export?format=json` | 200, application/json | curl | ✅ 自动 |
| ETW-HIST-018 | 导出 CSV | 存在任务 | `GET /api/history/{task_id}/export?format=csv` | 200, text/csv | curl | ✅ 自动 |

#### 前端 UI (ETW-UI)

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| ETW-UI-001 | 上传交互 | 浏览器 5173 | 1. 拖拽 CSV 2. 选 target 3. 选 intensity 4. 提交 | 上传进度, 列名下拉, 任务卡片创建 | 截图 | ⚠️ 人工 |
| ETW-UI-002 | 实时日志 | 任务运行中 | 观察 NDJSON 流 | 日志逐行渲染, 滚动跟随 | 截图 | ⚠️ 人工 |
| ETW-UI-003 | 结果图片网格 | 任务完成 | 查看结果区 | 图片缩略图网格, 点击放大 | 截图 | ⚠️ 人工 |
| ETW-UI-004 | 历史对比视图 | 多任务 | 1. 勾选 2 个 2. 点击对比 | 对比网格 2 列, 指标差异高亮 | 截图 | ⚠️ 人工 |
| ETW-UI-005 | 响应式 75% | 浏览器 | Ctrl+- | 布局正常 | 截图 | ⚠️ 人工 |
| ETW-UI-006 | 响应式 150% | 浏览器 | Ctrl+= | 布局正常 | 截图 | ⚠️ 人工 |
| ETW-UI-007 | 移动端 ≤640px | DevTools | 375×667 | 单列, 表单堆叠 | 截图 | ⚠️ 人工 |

---

## 第三部分: CLI 工具测试矩阵

### 3.1 trace-engine CLI (run_cli.py)

路径: `TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\run_cli.py`

子命令 (实际为 env/demo/real/clean, 非任务描述中的 real/sim/quick — 以代码为准):

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| TEC-001 | 无参数帮助 | - | `python run_cli.py` | 退出码 0, 输出用法 + COMMANDS 列表 (env/demo/real/clean) | stdout 检查 | ✅ 自动 |
| TEC-002 | env 子命令 | Python 环境 | `python run_cli.py env` | 输出 Python 版本, graphviz 状态, DoWhy/causallearn 可用性 | stdout 含 "Python:" | ✅ 自动 |
| TEC-003 | demo 子命令 | 依赖已装 | `PYTHONIOENCODING=utf-8 python run_cli.py demo` | 输出六战士管线阶段日志, 生成 outputs/demo/ 产物 | ls outputs/demo/ | ✅ 自动 |
| TEC-004 | real 子命令 (llama 预设) | 缓存文件 + LLaMA 模型 | `python run_cli.py real --preset llama` | 输出真实 TRACE 管线, 生成 outputs/real/ | ls outputs/real/ | ✅ 自动 |
| TEC-005 | real 子命令 (default 预设) | 缓存文件 | `python run_cli.py real --preset default` | 同 TEC-004, 参数差异 | ls | ✅ 自动 |
| TEC-006 | real 子命令 (standard 预设) | 缓存文件 | `python run_cli.py real --preset standard` | 同上 | ls | ✅ 自动 |
| TEC-007 | real 子命令 (deep 预设) | 缓存文件 | `python run_cli.py real --preset deep` | 同上, 更深参数 | ls | ✅ 自动 |
| TEC-008 | real 子命令 (archival 预设) | 缓存文件 | `python run_cli.py real --preset archival` | 同上 | ls | ✅ 自动 |
| TEC-009 | clean 子命令 | outputs/ 有产物 | `python run_cli.py clean` | outputs/demo, outputs/real, outputs/cache 清空 | ls | ✅ 自动 |
| TEC-010 | 非法子命令 | - | `python run_cli.py invalid` | 退出码 0 (走帮助分支), 输出用法 | stdout | ✅ 自动 |
| TEC-011 | graphviz 自动配置 | GRAPHVIZ_BIN_DIR 未设 | `python run_cli.py env` | 自动探测 graphviz 并配置 PATH | stdout 含 graphviz 状态 | ✅ 自动 |
| TEC-012 | presets.yaml 一致性 | - | 对比 `presets.yaml` 与 `presets.load_presets()` | 5 个预设键一致 (default/standard/deep/archival/llama) | Python 脚本断言 | ✅ 自动 |
| TEC-013 | 六战士单元测试 | - | `pytest tests/test_six_warriors.py -v` | 全部通过 | pytest 退出码 0 | ✅ 自动 |
| TEC-014 | presets 单元测试 | - | `pytest tests/test_presets.py -v` | 全部通过 | pytest | ✅ 自动 |
| TEC-015 | 反事实桥接测试 | - | `pytest tests/test_counterfactual_bridge.py -v` | 全部通过 | pytest | ✅ 自动 |

### 3.2 edm-takens CLI (run_pipeline.py)

路径: `Skill\edm-takens\run_pipeline.py`

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| ETC-001 | 默认参数运行 | game_log.csv 存在 | `python run_pipeline.py` | 输出 EDM 管线日志, 生成 results/ 产物 | ls results/ | ✅ 自动 |
| ETC-002 | 指定数据集 | - | `python run_pipeline.py --data src/data/game_log.csv --target result` | 同 ETC-001 | ls | ✅ 自动 |
| ETC-003 | auto_fix 开启 | - | `python run_pipeline.py --auto-fix` | 日志含 "auto-fix" 修正信息 | stdout grep | ✅ 自动 |
| ETC-004 | report-only 模式 | - | `python run_pipeline.py --report-only` | 仅输出环境报告, 不计算 | stdout 含 "report" | ✅ 自动 |
| ETC-005 | full-analysis 模式 | - | `python run_pipeline.py --full-analysis` | 跑 pipeline + 交叉验证 + 解释链 | ls results/ | ✅ 自动 |
| ETC-006 | 自定义 q | - | `python run_pipeline.py --q 5` | 使用 q=5 嵌入维 | stdout | ✅ 自动 |
| ETC-007 | 自定义 max-e | - | `python run_pipeline.py --max-e 10` | 搜索至 E=10 | stdout | ✅ 自动 |
| ETC-008 | 环境变量生效 | - | `MPLBACKEND=Agg python run_pipeline.py --report-only` | 无 matplotlib 显示后端错误 | stdout 无 traceback | ✅ 自动 |
| ETC-009 | CCM 单元测试 | - | `pytest tests/test_ccm_canonical.py -v` | 全部通过 | pytest | ✅ 自动 |
| ETC-010 | 路由单元测试 | - | `pytest tests/test_router.py -v` | 全部通过 | pytest | ✅ 自动 |
| ETC-011 | HAVOK 单元测试 | - | `pytest tests/test_havok.py tests/test_havok_forcing.py -v` | 全部通过 | pytest | ✅ 自动 |
| ETC-012 | 置换检验测试 | - | `pytest tests/test_surrogate_test.py -v` | 全部通过 | pytest | ✅ 自动 |
| ETC-013 | 数据质量测试 | - | `pytest tests/test_data_quality.py -v` | 全部通过 | pytest | ✅ 自动 |
| ETC-014 | 列重映射测试 | - | `pytest tests/test_column_remap.py -v` | 全部通过 | pytest | ✅ 自动 |
| ETC-015 | 分析 profile 测试 | - | `pytest tests/test_analysis_profiles.py -v` | 全部通过 | pytest | ✅ 自动 |
| ETC-016 | sovereign_havok 测试 | - | `pytest tests/test_sovereign_havok.py -v` | 全部通过 | pytest | ✅ 自动 |

---

## 第四部分: 跨项目集成测试

### 4.1 trace-engine-web → trace-to-edm 数据流

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| INT-001 | 轨迹 CSV 传递 | 两服务运行 | 1. TEW 提交 LIGHT 分析 (写 work/outputs/{id}/result.json) 2. TTE work-scan 发现该 UUID 3. TTE replay 该 UUID | TTE 轨迹 CSV 新增 1 行, columns 含 ate/edge_count 等 L1 字段 | curl + readTrajectoryCSV | ✅ 自动 |
| INT-002 | UUID 输入文本复用 | INT-001 通过 | TTE `GET /api/work-uuid/{id}/text` | 返回 TEW 原始输入文本 (work/inputs/{id}.txt) | curl + jq | ✅ 自动 |
| INT-003 | 跨项目 CORS | 两服务运行 | 浏览器在 3000 页面 fetch 3100 /api/status | CORS 放行 (shared auth_middleware) | 浏览器 DevTools | ⚠️ 人工 |
| INT-004 | API Key 跨项目 | 设置 CROSS_PROJECT_API_KEY | 1. TEW 带 key 调 TTE 2. 无 key 调 TTE | 带 key 通过, 无 key 401 | curl | ✅ 自动 |

### 4.2 trace-to-edm → edm-takens-web 数据流

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| INT-005 | EDM 触发转发 | 轨迹 ≥15 行, ETW 8000 运行 | `POST 3100/api/edm/trigger` body `{"target":"ate","q":3}` | TTE 调用 bridge.py → ETW /api/analyze, 返回 EDM 结果 | curl + jq | ✅ 自动 |
| INT-006 | EDM 轮询代理 | INT-005 通过 | `GET 3100/api/edm/poll/{job_id}` | TTE 代理转发 ETW 8000 /api/analyze/jobs/{id} | curl | ✅ 自动 |
| INT-007 | EDM 后端不可达降级 | 停止 ETW 8000 | `GET 3100/api/edm/poll/xxx` | 502, hint 提示启动 edm-takens-web | curl | ✅ 自动 |
| INT-008 | EDM 超时降级 | mock 8000 不响应 | `GET 3100/api/edm/poll/xxx` | 504 | curl | ✅ 自动 |

### 4.3 端到端完整管道

| 测试 ID | 测试名称 | 前置条件 | 测试步骤 | 预期结果 | 验证方法 | 自动化 |
|---------|----------|----------|----------|----------|----------|--------|
| INT-009 | 完整管道 LIGHT | 三服务 + 两 CLI 可用 | 1. TEW `/api/analyze-text` light 分析文本 → result.json 2. TTE `/api/replay-uuids` 回填该 UUID → 轨迹 +1 行 3. 重复 ≥15 次 (或批量 CSV) 4. TTE `/api/edm/trigger` → EDM 结果 5. ETW `/api/history` 查看结果 | 全链路无错误, 最终 EDM 报告含 ρ_high/ρ_mid/HAVOK 指标 | curl 全链路脚本 | ✅ 自动 |
| INT-010 | 完整管道 DEEP | 同 INT-009 | 同 INT-009 但 mode=deep | 轨迹含 ccm_coverage_pct>0, refuted_count>0, EDM 输入更丰富 | curl 脚本 | ✅ 自动 |
| INT-011 | 完整管道 SUPER | LLaMA Worker ready | 同 INT-009 但 mode=super | TEW SUPER 完成, TTE 回填, ETW EDM | curl 脚本 (长耗时) | ⚠️ 人工 |
| INT-012 | 人话版报告端到端 | INT-009 通过 | `GET 3100/api/trajectory/report?format=html` | HTML 报告含全部 88 列层级卡片, 趋势箭头, EDM 就绪标识 | curl + grep "<details" | ✅ 自动 |
| INT-013 | CLI + Web 混合 | - | 1. trace-engine CLI `real --preset llama` 生成产物 2. TTE 工作目录扫描发现 3. ETW 分析 | CLI 产物被 Web 项目消费 | 手动 + curl | ⚠️ 人工 |
| INT-014 | edm-takens CLI + Web | - | 1. ETC-005 生成 results/ 2. ETW /api/history 显示该任务 | CLI 产物在 Web 历史可见 | ls + curl | ⚠️ 人工 |

---

## 第五部分: 回归测试检查清单

### 5.1 每次代码变更后必跑

| 检查项 | 命令 | 通过标准 | 自动化 |
|--------|------|----------|--------|
| trace-engine-web 健康检查 | `curl /api/health` | status ∈ {healthy, degraded} | ✅ |
| trace-to-edm 健康检查 | `curl /api/health` | status:ok | ✅ |
| edm-takens-web 健康检查 | `curl /api/health` | status:ok | ✅ |
| trace-engine-web 配置加载 | `curl /api/config` | bridgeParamSchema 非空 | ✅ |
| trace-to-edm 状态 | `curl /api/status` | trajectory.rows ≥0 | ✅ |
| edm-takens-web 数据集 | `curl /api/datasets` | datasets 数组非空 | ✅ |
| trace-engine 单元测试 | `pytest tests/ -v` | 全过 | ✅ |
| edm-takens 单元测试 | `pytest tests/ -v` | 全过 | ✅ |
| trace-engine-web API 测试 | `python tests/test_api.py` | 全过 | ✅ |
| trace-engine-web 上传测试 | `python tests/test_upload.py` | 全过 | ✅ |

### 5.2 算法正确性验证

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| presets 一致性 | 对比 `presets.yaml` (TEC-012) 与 `/api/presets` (TEW-INF-005) | 5 个预设键完全一致: default/standard/deep/archival/llama |
| CCM 收敛性 | ETC-009 pytest | CCM ρ 单调递增趋势, 收敛阈值达标 |
| p 值 +1 修正 | 检查 surrogate_test.py 输出 | permutation_p_value ∈ [0,1], 无负值, +1 修正生效 |
| 八正道正交性 | TTE-INF-005 | Frobenius 距离矩阵对角线接近 0, 非对角显著大 |
| ATE 符号正确性 | TEW-LIGHT-002 | 抑制关系 ATE<0, 促进 ATE>0, 无线性 ATE≈0 |
| LIGHT 模式 CCM=0 | TEW-LIGHT-002 | ccm_coverage_pct=0 (LIGHT 不跑 CCM) |
| DEEP 模式 CCM>0 | TEW-DEEP-001 | ccm_coverage_pct>0 |
| LIGHT 模式 refuted=0 | TEW-LIGHT-002 | refuted_count=0 |
| DEEP 模式 refuted>0 | TEW-DEEP-001 | refuted_count>0 |
| 差分首行空 | TTE-LIGHT-006 报告 | dz_ 首行为空, d2z_ 前两行为空 |
| zscore 标准化 | 报告检查 | z_pca/z_八正道 均值≈0, 标准差≈1 |

### 5.3 文档同步验证

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| 端点数一致 | server.js 注释 vs 实际 router | TEW 26 routes, TTE 33 routes |
| 缓存戳一致 | /api/config buildInfo vs package.json version | 版本号匹配 |
| README API 表 | 对比 README §API 端点表 vs 实际 | 端点数 + 路径 + 方法一致 |
| Schema 同步 | bridge_schema.json vs /api/schema | 字段一致 |
| presets.yaml 同步 | presets.yaml vs /api/presets | 键一致 |
| CHANGELOG 版本 | docs/CHANGELOG.md vs package.json | 版本号匹配 |
| DEPENDENCY_MATRIX | Docs/DEPENDENCY_MATRIX.md vs 实际依赖 | 依赖项匹配 |
| DOC_SYNC_REPORT | Docs/DOC_SYNC_REPORT.md | 无未同步项 |

### 5.4 安全回归

| 检查项 | 测试 ID | 通过标准 |
|--------|---------|----------|
| 路径遍历防护 | TTE-LIGHT-003/004, TEW-ERR-009/010, ETW-DS-009 | 全部 400 |
| Python 注入防护 | TTE-DS-007 (update-ts), TTE-PROJ-002 | JSON 序列化传参, 无拼接 |
| CORS 通配符拒绝 | TTE-INF-010, ETW-INF-005/006 | 拒绝 *, 拒绝 credentials+* |
| 限流生效 | TEW-INF-009 | 11 次/分钟 → 429 |
| 鉴权分级 | TEW-HIST-005/006 | 管理端点需 API Key |
| 文件类型白名单 | TEW-LIGHT-007, ETW-DS-002 | 仅 .txt/.md (TEW), 仅 .csv (ETW) |
| 文件大小限制 | ETW-DS-003 | >50MB → 413 |
| 二进制内容拒绝 | ETW-DS-004 | NUL 字节 → 415 |
| Host 收窄 | 默认 127.0.0.1 | 不暴露 0.0.0.0 |
| UUID 白名单 | TTE-REPLAY-005/006 | 仅 [A-Za-z0-9_-]{1,64} |

---

## 附录 A: 验证脚本示例

### A.1 健康检查一键脚本 (PowerShell)

```powershell
# health_check_all.ps1 — 三服务健康检查
$services = @(
    @{ Name = "trace-engine-web"; Url = "http://127.0.0.1:3000/api/health" },
    @{ Name = "trace-to-edm";    Url = "http://127.0.0.1:3100/api/health" },
    @{ Name = "edm-takens-web";  Url = "http://127.0.0.1:8000/api/health" }
)
foreach ($s in $services) {
    try {
        $r = Invoke-RestMethod -Uri $s.Url -TimeoutSec 5
        Write-Host "[OK]   $($s.Name): $($r.status)" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $($s.Name): $($_.Exception.Message)" -ForegroundColor Red
    }
}
```

### A.2 TEW LIGHT 端到端 curl 脚本

```bash
#!/bin/bash
# tew_light_e2e.sh — trace-engine-web LIGHT 模式端到端
set -e
BASE=http://127.0.0.1:3000
TEXT=$(cat "f:/攻略/研发测试/TRACE Engine(EDM-Takens CCM)/trace-engine-web/sample_input.txt")

echo "=== 1. 健康检查 ==="
curl -s "$BASE/api/health" | jq -r '.status'

echo "=== 2. 配置加载 ==="
curl -s "$BASE/api/config" | jq -r '.bridgeParamSchema | keys | length'

echo "=== 3. 同步分析 ==="
RESP=$(curl -s -X POST "$BASE/api/analyze-text" \
    -H "Content-Type: application/json" \
    -d "{\"text\":\"$TEXT\",\"mode\":\"light\"}")
JOB_ID=$(echo "$RESP" | jq -r '.data.id')
echo "Job ID: $JOB_ID"

echo "=== 4. 结果获取 ==="
curl -s "$BASE/api/result/$JOB_ID" | jq -r '.ate, .edge_count, .ccm_coverage_pct'

echo "=== 5. 报告导出 ==="
curl -s "$BASE/api/report/$JOB_ID" | head -5

echo "=== 6. 缓存命中 ==="
curl -s -X POST "$BASE/api/analyze-text" \
    -H "Content-Type: application/json" \
    -d "{\"text\":\"$TEXT\",\"mode\":\"light\"}" | jq -r '.cached'
```

### A.3 TTE 轨迹 + EDM 触发 Python 脚本

```python
# tte_edm_trigger.py — trace-to-edm 轨迹检查 + EDM 触发
import requests, json, time

BASE = "http://127.0.0.1:3100"

# 1. 状态检查
status = requests.get(f"{BASE}/api/status").json()
print(f"轨迹行数: {status['trajectory']['rows']}")
print(f"EDM 就绪: {status['trajectory']['edm_ready']}")
assert status['trajectory']['edm_ready'], "轨迹不足 15 行, 无法触发 EDM"

# 2. EDM 触发
resp = requests.post(f"{BASE}/api/edm/trigger", json={
    "target": "ate", "q": 3
}, timeout=120)
result = resp.json()
print(f"EDM 成功: {result.get('success')}")
print(f"ρ_high: {result.get('edm_rho_high')}")
print(f"ρ_mid:  {result.get('edm_rho_mid')}")

# 3. 人话版报告
md = requests.get(f"{BASE}/api/trajectory/report").text
print(f"报告长度: {len(md)} 字符")
assert "## 1. 概览" in md
assert "## 2. 指标详解" in md
```

### A.4 ETW NDJSON 流监听 Python 脚本

```python
# etw_stream.py — edm-takens-web 任务日志流监听
import requests

BASE = "http://127.0.0.1:8000"
JOB_ID = "your-job-id-here"

with requests.get(f"{BASE}/api/analyze/jobs/{JOB_ID}/stream",
                  stream=True, timeout=300) as r:
    for line in r.iter_lines(decode_unicode=True):
        if line:
            import json
            evt = json.loads(line)
            print(f"[{evt.get('level','info')}] {evt.get('message','')}")
            if evt.get('event') == 'done':
                break
```

### A.5 跨项目完整管道脚本

```python
# full_pipeline.py — 文本 → TRACE → EDM 完整管道
import requests, time, json

TEW = "http://127.0.0.1:3000"
TTE = "http://127.0.0.1:3100"
ETW = "http://127.0.0.1:8000"

TEXT = open("sample_input.txt", encoding="utf-8").read()

# 阶段 1: TEW LIGHT 分析
print("[1/4] TEW LIGHT 分析...")
r = requests.post(f"{TEW}/api/analyze-text",
                  json={"text": TEXT, "mode": "light"}).json()
uuid = r["data"]["id"]
print(f"  UUID: {uuid}")

# 阶段 2: TTE 回填该 UUID
print("[2/4] TTE 回填 UUID...")
with requests.post(f"{TTE}/api/replay-uuids",
                   json={"uuids": [uuid]}, stream=True, timeout=300) as r:
    for line in r.iter_lines(decode_unicode=True):
        if line and "done" in line:
            print(f"  {line[:120]}")

# 阶段 3: 检查 EDM 就绪
print("[3/4] 检查 EDM 就绪...")
status = requests.get(f"{TTE}/api/status").json()
rows = status["trajectory"]["rows"]
print(f"  轨迹行数: {rows}")
assert rows >= 15, f"轨迹仅 {rows} 行, 需 ≥15"

# 阶段 4: 触发 EDM
print("[4/4] 触发 EDM 分析...")
edm = requests.post(f"{TTE}/api/edm/trigger",
                    json={"target": "ate", "q": 3}, timeout=120).json()
print(f"  EDM success: {edm.get('success')}")
print(f"  ρ_high: {edm.get('edm_rho_high')}")
print("=== 完整管道成功 ===")
```

### A.6 响应式布局自动化 (Playwright 示例)

```javascript
// rwd_test.spec.js — Playwright 响应式测试
const { test, expect } = require('@playwright/test');

const viewports = [
    { name: '75%', width: 1706, height: 960 },   // 1920/0.75
    { name: '100%', width: 1280, height: 720 },
    { name: '125%', width: 1024, height: 576 },  // 1280/1.25
    { name: '150%', width: 853, height: 480 },   // 1280/1.5
    { name: 'mobile-375', width: 375, height: 667 },
];

for (const vp of viewports) {
    test(`trace-engine-web @ ${vp.name}`, async ({ page }) => {
        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto('http://127.0.0.1:3000');
        // 检查无横向滚动
        const scrollX = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(scrollX).toBeLessThanOrEqual(5);
        await page.screenshot({ path: `screenshots/tew-${vp.name}.png`, fullPage: true });
    });
}
```

---

## 附录 B: 人工 vs 自动化标注

### B.1 标注图例

- ✅ 自动 — 可通过 curl / Python 脚本 / pytest 自动执行, 无需人眼判断
- ⚠️ 人工 — 需要浏览器人工观察视觉布局 / SSE 实时行为 / 长耗时任务

### B.2 统计

| 类别 | 总数 | 自动 | 人工 |
|------|------|------|------|
| TEW (trace-engine-web) | 47 | 37 | 10 |
| TTE (trace-to-edm) | 48 | 42 | 6 |
| ETW (edm-takens-web) | 32 | 25 | 7 |
| CLI (trace-engine) | 15 | 15 | 0 |
| CLI (edm-takens) | 16 | 16 | 0 |
| 集成测试 | 14 | 9 | 5 |
| **总计** | **172** | **144** | **28** |

自动化率: **83.7%** (144/172)

### B.3 人工测试执行建议

1. **响应式布局批次** (15 项): 一次浏览器会话内完成所有 RWD 测试, 每个项目按 75→100→125→150→mobile 顺序
2. **SSE 实时行为批次** (5 项): 观察日志滚动、进度条、断线重连
3. **跨项目导航批次** (3 项): 三项目间切换、主题一致性、隧道模式
4. **SUPER 模式批次** (3 项): LLaMA 模型加载、速率预估、长耗时
5. **CLI + Web 混合批次** (2 项): CLI 产物被 Web 消费

### B.4 自动化测试执行顺序建议

```bash
# 1. 启动三服务
# 2. 基础设施 (INF) 全自动
bash run_inf_tests.sh

# 3. 单元测试 (CLI)
cd trace-engine && pytest tests/ -v
cd edm-takens && pytest tests/ -v

# 4. 功能 E2E (curl 脚本)
bash run_tew_light.sh
bash run_tew_deep.sh
bash run_tte_light.sh
bash run_etw_analyze.sh

# 5. 跨项目集成
python full_pipeline.py

# 6. 响应式 (Playwright)
npx playwright test rwd_test.spec.js

# 7. 人工补测 (按 B.3 批次)
```

---

## 文档维护

- 文档版本: R26-1.0
- 生成依据: 实际代码审计 (server.js / api.py / run_cli.py / run_pipeline.py / routes/*.js / routes/*.py)
- 端点数依据: trace-engine-web 26 routes (server.js 注释), trace-to-edm 33 routes (server.js 注释), edm-takens-web FastAPI 路由 (api.py + routes/)
- CLI 子命令依据: `COMMANDS` dict in run_cli.py (env/demo/real/clean)
- 更新触发: 每次新增端点 / 新增 CLI 子命令 / 修改响应式断点时需同步本文档
- 关联文档: `Docs/05-trace-engine-web.md`, `Docs/06-trace-to-edm.md`, `Docs/03-edm-takens-web.md`, `Docs/04-trace-engine.md`, `Docs/02-edm-takens.md`, `Docs/DEPENDENCY_MATRIX.md`
