# 三大WEB MCP接口档案

> **版本**：v1.0 (2026-08-02)
> **覆盖范围**：trace-engine-web / trace-to-edm / edm-takens-web
> **协议版本**：MCP `2024-11-05` (JSON-RPC 2.0 over HTTP)
> **总工具数**：21（trace-engine-web:7 + trace-to-edm:8 + edm-takens-web:6）
> **核查脚本**：`TRACE Engine(EDM-Takens CCM)/test_mcp_protocol.py`

---

## 一、设计原则

| 原则 | 说明 |
|------|------|
| **适配层而非替代层** | MCP 模块不修改任何现有路由代码，作为可插拔适配层包装现有 HTTP API |
| **localhost fetch 复用** | 通过 `127.0.0.1:PORT` 调用现有路由，继承校验/错误处理/trace_id/缓存控制 |
| **零新依赖** | Node.js 用内置 `http`；Python 用 `urllib.request` |
| **单一端点** | 所有 MCP 调用走 `POST /mcp`，方法由 JSON-RPC `method` 字段决定 |

---

## 二、协议规范

### 2.1 传输层

- **协议**：JSON-RPC 2.0
- **传输**：HTTP POST
- **端点**：`POST /mcp`（三大WEB统一）
- **Content-Type**：`application/json`
- **协议版本**：`2024-11-05`

### 2.2 三步走方法

| 方法 | 用途 | 必填 params |
|------|------|-------------|
| `initialize` | 协议握手，返回 serverInfo + protocolVersion | 无 |
| `tools/list` | 列出可用工具 | 无 |
| `tools/call` | 调用工具 | `name` (string), `arguments` (object) |

### 2.3 JSON-RPC 错误码

| 错误码 | 含义 | 触发条件 |
|--------|------|----------|
| `-32600` | Invalid Request | `jsonrpc` 字段不等于 `"2.0"` |
| `-32601` | Method not found | `method` 非 `initialize`/`tools/list`/`tools/call` |
| `-32602` | Invalid params | `tools/call` 缺 `name` 字段，或工具名不存在 |
| `-32603` | Internal error | 工具调用异常（路由不可达/超时等） |

### 2.4 响应结构

**成功响应**：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{ "type": "text", "text": "<工具返回内容>" }],
    "isError": false
  }
}
```

**错误响应**：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": { "code": -32602, "message": "params.name is required" }
}
```

---

## 三、三大WEB服务矩阵

| WEB | 端口 | 技术栈 | MCP模块文件 | 入口注册 |
|-----|------|--------|-------------|----------|
| trace-engine-web | 3000 | Node.js + Express | `trace-engine-web/mcp/index.js` | `server.js:184-185` |
| trace-to-edm | 3100 | Node.js + Express + Python bridge | `trace-to-edm/mcp.js` | `server.js:204-205` |
| edm-takens-web | 8000 | Python FastAPI + Vite | `edm-takens-web/backend/mcp.py` | `api.py:279-280` |

### 3.1 服务启动

| WEB | 启动命令 | 健康检查 |
|-----|----------|----------|
| trace-engine-web | `node server.js` | `GET /api/health` → `{success, status:healthy}` |
| trace-to-edm | `node server.js` | `GET /api/version` → `{success, service, version}` |
| edm-takens-web | `python run_backend.py` | `GET /api/health` → `{status:ok, time}` |

### 3.2 服务发现端点（GET /mcp）

浏览器访问 `GET /mcp` 可获取服务信息：
```json
{
  "service": "trace-engine-web-mcp",
  "version": "0.1.0",
  "protocolVersion": "2024-11-05",
  "endpoint": "POST /mcp",
  "methods": ["initialize", "tools/list", "tools/call"],
  "toolCount": 7,
  "tools": ["analyze_text", "list_jobs", "get_job", "get_job_detail", "get_result", "export_md", "health"]
}
```

---

## 四、trace-engine-web 工具清单（7个）

> 因果推断特装型 — 输入文本返回 ATE、因果边、概念列表

### 4.1 analyze_text（因果推断分析）

| 字段 | 值 |
|------|-----|
| **name** | `analyze_text` |
| **description** | 对文本进行因果推断分析（TRACE Engine）。输入描述因果关系的文本，返回 ATE、因果边、概念列表等。短文本（<10词）会被拒绝。 |
| **复用路由** | `POST /api/analyze-text` |

**inputSchema**：
```json
{
  "type": "object",
  "properties": {
    "text": { "type": "string", "description": "待分析的文本（建议 ≥10 个有效词）" },
    "mode": { "type": "string", "enum": ["light", "deep", "super"], "default": "light",
              "description": "分析模式: light=快速共现, deep=六战士, super=LLaMA ΔNLL" }
  },
  "required": ["text"]
}
```

**返回示例**：
```json
{
  "success": true,
  "cached": false,
  "traceId": "77dd5bb4-3a30-48b4-8343-bdd2071c637a",
  "data": {
    "id": "e03f37fa-aaf2-4f33-88e7-ca3baf9d9ee0",
    "result": { "success": true, "ate": 0.42, "edges": [...], "concepts": [...] }
  }
}
```

### 4.2 list_jobs（列出任务）

| 字段 | 值 |
|------|-----|
| **name** | `list_jobs` |
| **description** | 列出因果推断任务历史（最近50条）。 |
| **复用路由** | `GET /api/jobs` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 4.3 get_job（查询任务状态）

| 字段 | 值 |
|------|-----|
| **name** | `get_job` |
| **description** | 查询单个任务的状态和元数据。 |
| **复用路由** | `GET /api/jobs/:id` |

**inputSchema**：
```json
{
  "type": "object",
  "properties": { "id": { "type": "string", "description": "任务 UUID" } },
  "required": ["id"]
}
```

### 4.4 get_job_detail（任务详情）

| 字段 | 值 |
|------|-----|
| **name** | `get_job_detail` |
| **description** | 获取任务详情（聚合输入文本 + result.json + report.md）。 |
| **复用路由** | `GET /api/jobs/:id/detail` |
| **inputSchema** | 同 `get_job` |

### 4.5 get_result（完整结果）

| 字段 | 值 |
|------|-----|
| **name** | `get_result` |
| **description** | 获取任务的完整分析结果（result.json）。 |
| **复用路由** | `GET /api/result/:id` |
| **inputSchema** | 同 `get_job` |

### 4.6 export_md（人话版报告）

| 字段 | 值 |
|------|-----|
| **name** | `export_md` |
| **description** | 导出任务的人话版 Markdown 报告（非技术读者可理解）。 |
| **复用路由** | `GET /api/jobs/:id/export/md` |
| **inputSchema** | 同 `get_job` |

### 4.7 health（健康检查）

| 字段 | 值 |
|------|-----|
| **name** | `health` |
| **description** | 检查服务健康状态（skill/python 就绪情况）。 |
| **复用路由** | `GET /api/health` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

---

## 五、trace-to-edm 工具清单（8个）

> TRACE-TO-EDM 桥接操纵台 — 文本管线 + EDM触发 + 轨迹查询

### 5.1 run_pipeline（运行文本管线）

| 字段 | 值 |
|------|-----|
| **name** | `run_pipeline` |
| **description** | 运行 TRACE 文本管线（处理数据集中的待处理条目）。LIGHT 模式用 jieba 分词，DEEP 模式用六战士算法。 |
| **复用路由** | `POST /api/run` |

**inputSchema**：
```json
{
  "type": "object",
  "properties": {
    "mode": { "type": "string", "enum": ["light", "deep"], "default": "light",
              "description": "TRACE 模式: light=1-3s/条(jieba), deep=10-60s/条(六战士)" }
  }
}
```

### 5.2 trigger_edm（触发EDM分析）

| 字段 | 值 |
|------|-----|
| **name** | `trigger_edm` |
| **description** | 触发 EDM 分析（含反馈检测），基于轨迹数据进行动力学重建和预测。 |
| **复用路由** | `POST /api/edm/trigger` |

**inputSchema**：
```json
{
  "type": "object",
  "properties": {
    "target": { "type": "string", "default": "ate",
                "description": "预测目标: ate/adj_density/max_delta_nll/ci_width/edge_count/ccm_coverage_pct" },
    "steps": { "type": "integer", "default": 3, "description": "预测步数: 1/3/5/10" }
  }
}
```

### 5.3 get_trajectory（轨迹查询）

| 字段 | 值 |
|------|-----|
| **name** | `get_trajectory` |
| **description** | 查询轨迹数据（TRACE 产出的因果指标时间序列）。 |
| **复用路由** | `GET /api/trajectory` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 5.4 list_projects（列出项目）

| 字段 | 值 |
|------|-----|
| **name** | `list_projects` |
| **description** | 列出所有项目及其数据条目数。 |
| **复用路由** | `GET /api/projects` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 5.5 list_models（列出模型）

| 字段 | 值 |
|------|-----|
| **name** | `list_models` |
| **description** | 列出可用的 LLM 模型（Qwen2.5-1.5B/3B 等）。 |
| **复用路由** | `GET /api/models` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 5.6 get_dataset（数据集状态）

| 字段 | 值 |
|------|-----|
| **name** | `get_dataset` |
| **description** | 获取当前项目的数据集（回填条目 + 文本条目 + 处理状态）。 |
| **复用路由** | `GET /api/dataset` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 5.7 health（健康检查）

| 字段 | 值 |
|------|-----|
| **name** | `health` |
| **description** | 检查服务健康状态。 |
| **复用路由** | `GET /api/health` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 5.8 version（版本查询）

| 字段 | 值 |
|------|-----|
| **name** | `version` |
| **description** | 获取服务版本信息。 |
| **复用路由** | `GET /api/version` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

---

## 六、edm-takens-web 工具清单（6个）

> EDM-Takens Observatory — 拓扑重建动力学分析

### 6.1 list_datasets（列出数据集）

| 字段 | 值 |
|------|-----|
| **name** | `list_datasets` |
| **description** | 列出已上传的 CSV 数据集文件名列表。 |
| **复用路由** | `GET /api/datasets` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 6.2 run_analysis（运行EDM分析）

| 字段 | 值 |
|------|-----|
| **name** | `run_analysis` |
| **description** | 运行 EDM-Takens 分析（从拓扑重建动力学）。需要先选择数据集和目标列。 |
| **复用路由** | `POST /api/analyze` |

**inputSchema**：
```json
{
  "type": "object",
  "properties": {
    "dataset": { "type": "string", "description": "数据集文件名（如 game_log.csv）" },
    "target_col": { "type": "string", "description": "目标列名" },
    "variables": { "type": "string", "description": "分析变量（逗号分隔，留空自动选前6个）" },
    "q": { "type": "integer", "description": "嵌入维度（留空自动检测，范围2-64）" },
    "profile": { "type": "string", "enum": ["auto", "light", "medium", "heavy"], "default": "auto" }
  },
  "required": ["dataset", "target_col"]
}
```

### 6.3 get_job（查询任务状态）

| 字段 | 值 |
|------|-----|
| **name** | `get_job` |
| **description** | 查询 EDM 分析任务的状态和结果。 |
| **复用路由** | `GET /api/analyze/jobs/{job_id}` |

**inputSchema**：
```json
{
  "type": "object",
  "properties": { "job_id": { "type": "string", "description": "任务 ID" } },
  "required": ["job_id"]
}
```

### 6.4 list_history（历史记录）

| 字段 | 值 |
|------|-----|
| **name** | `list_history` |
| **description** | 列出历史分析记录。 |
| **复用路由** | `GET /api/history` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

### 6.5 get_history_detail（历史详情）

| 字段 | 值 |
|------|-----|
| **name** | `get_history_detail` |
| **description** | 获取历史任务的详情（含结果摘要）。 |
| **复用路由** | `GET /api/history/{task_id}` |

**inputSchema**：
```json
{
  "type": "object",
  "properties": { "task_id": { "type": "string", "description": "历史任务 ID" } },
  "required": ["task_id"]
}
```

### 6.6 health（健康检查）

| 字段 | 值 |
|------|-----|
| **name** | `health` |
| **description** | 检查 EDM-Takens 服务健康状态。 |
| **复用路由** | `GET /api/health` |
| **inputSchema** | `{ "type": "object", "properties": {} }` |

---

## 七、调用示例

### 7.1 curl（PowerShell Invoke-WebRequest）

```powershell
# Step 1: initialize
$body = @{ jsonrpc = "2.0"; method = "initialize"; id = 1 } | ConvertTo-Json
(Invoke-WebRequest -Uri "http://127.0.0.1:3000/mcp" -Method POST -Body $body -ContentType "application/json").Content

# Step 2: tools/list
$body = @{ jsonrpc = "2.0"; method = "tools/list"; id = 2 } | ConvertTo-Json
(Invoke-WebRequest -Uri "http://127.0.0.1:3000/mcp" -Method POST -Body $body -ContentType "application/json").Content

# Step 3: tools/call — analyze_text
$body = @{
  jsonrpc = "2.0"; method = "tools/call"; id = 3
  params = @{
    name = "analyze_text"
    arguments = @{
      text = "算法推荐导致信息茧房，信息茧房加剧观点极化。"
      mode = "light"
    }
  }
} | ConvertTo-Json -Depth 5
(Invoke-WebRequest -Uri "http://127.0.0.1:3000/mcp" -Method POST -Body $body -ContentType "application/json").Content
```

### 7.2 Python（urllib）

```python
import json
import urllib.request

def mcp_call(port, method, params=None, req_id=1):
    body = {'jsonrpc': '2.0', 'method': method, 'id': req_id}
    if params:
        body['params'] = params
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}/mcp',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())

# 三步走
print(mcp_call(3000, 'initialize'))
print(mcp_call(3000, 'tools/list'))
print(mcp_call(3000, 'tools/call', {
    'name': 'analyze_text',
    'arguments': {'text': '算法推荐导致信息茧房。', 'mode': 'light'}
}))
```

### 7.3 Node.js（fetch）

```javascript
async function mcpCall(port, method, params, id = 1) {
  const body = { jsonrpc: '2.0', method, id };
  if (params) body.params = params;
  const r = await fetch(`http://127.0.0.1:${port}/mcp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  return await r.json();
}

await mcpCall(3000, 'initialize');
await mcpCall(3000, 'tools/list');
await mcpCall(3000, 'tools/call', {
  name: 'analyze_text',
  arguments: { text: '算法推荐导致信息茧房。', mode: 'light' }
});
```

---

## 八、运作核查

### 8.1 核查脚本

路径：`TRACE Engine(EDM-Takens CCM)/test_mcp_protocol.py`

**核查三步走**（每个WEB）：
1. `initialize` — 验证返回 serverInfo + protocolVersion
2. `tools/list` — 验证工具数 > 0
3. `tools/call health` — 验证 `isError=False`

**额外业务工具核查**：
- trace-engine-web → `analyze_text`（验证返回 traceId + result）
- trace-to-edm → `version`（验证返回版本号）
- edm-takens-web → `list_datasets`（验证返回数据集列表）

### 8.2 运行方式

```powershell
# 启动三大WEB（分别在新终端）
cd "f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web"; node server.js
cd "f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm"; node server.js
cd "f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\edm-takens-web"; python run_backend.py

# 运行核查
python "f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\test_mcp_protocol.py"
```

### 8.3 通过标准

| 核查项 | 通过标准 |
|--------|----------|
| initialize | 返回 `serverInfo.name` 非空 + `protocolVersion=2024-11-05` |
| tools/list | 工具数 > 0（trace-engine-web:7 / trace-to-edm:8 / edm-takens-web:6） |
| tools/call health | `isError=False` 且 `content[0].text` 非空 |
| 业务工具 | `isError=False` 且返回业务数据（traceId/version/datasets） |

---

## 九、同步与维护

### 9.1 便携目录同步

便携目录 `Skill/edm-takens-web/backend/` 需与工作目录 `TRACE Engine(EDM-Takens CCM)/edm-takens-web/backend/` 保持以下文件 SHA256 一致：

| 文件 | 同步方向 | 验证方式 |
|------|----------|----------|
| `mcp.py` | 工作目录 → 便携目录 | `Get-FileHash` SHA256 比对 |
| `api.py` | 工作目录 → 便携目录 | `Get-FileHash` SHA256 比对 |
| `edmtakens/*.py` | 双向 | `python sync_check.py` |

> **注**：trace-engine-web 和 trace-to-edm 不在便携目录 `Skill/` 下，仅工作目录维护。

### 9.2 sync_check.py 验证

```powershell
python "f:\攻略\研发测试\Skill\edm-takens-web\backend\sync_check.py"
```

预期输出：
```
源码汇总: 20 一致 / 2 预期差异 / 0 不一致 / 0 副本缺失
披露字段检查通过 (8 项)
文档同步检查通过
```

### 9.3 新增工具流程

1. 在 MCP 模块的 `TOOLS` 数组追加工具定义（含完整 `inputSchema`）
2. 在 `callTool`/`call_tool` 函数追加 `case` 分支，映射到现有 HTTP 路由
3. 在 `test_mcp_protocol.py` 追加业务工具核查用例
4. 同步 `mcp.py`/`mcp.js` 到便携目录（仅 edm-takens-web）
5. 更新本文档对应章节

---

## 十、便携目录运行时记忆清理（成本项目原则）

> **原则**：五大项目作为成本项目（便携式源码归档），不应保留运行时记忆产物。

### 10.1 应清理的运行时产物

| 项目 | 清理项 | 说明 |
|------|--------|------|
| edm-takens-web | `results/*` | 运行时分析结果 |
| edm-takens-web | `jobs.sqlite` | 任务数据库 |
| trace-engine-web | `work/inputs/*.txt` | 测试任务输入 |
| trace-engine-web | `work/outputs/<uuid>/` | 测试任务输出 |
| trace-engine-web | `work/job_history.json` | 任务历史 |
| trace-engine-web | `work/*.log` | 服务日志 |
| trace-engine-web | `tunnel_logs/*` | 隧道日志 |
| trace-to-edm | `data/outputs/_*` | 运行时回填结果 |
| trace-to-edm | `data/logs/*.log` | 服务日志 |
| trace-to-edm | `projects/_index.json` | 项目索引（运行时状态） |
| trace-to-edm | `projects/default/cache/` | 模型缓存（PCA/sacred vectors） |
| trace-to-edm | `projects/default/outputs/` | 待处理数据 |
| trace-to-edm | `projects/default/reports/` | 运行时报告 |
| trace-to-edm | `projects/default/dataset.json` | 数据集状态 |
| trace-to-edm | `projects/default/narrative_meta_trajectories*.csv` | 轨迹CSV |
| 所有项目 | `__pycache__/` | Python字节码缓存 |
| 所有项目 | `*.pyc` | Python字节码 |

### 10.2 应保留的骨架文件

| 项目 | 保留项 | 说明 |
|------|--------|------|
| trace-to-edm | `data/inputs/.gitkeep` | 输入目录占位 |
| trace-to-edm | `data/inputs/news_40_csv_input.csv` | 示例输入（开箱即用） |
| trace-to-edm | `data/outputs/.gitkeep` | 输出目录占位 |
| trace-to-edm | `projects/.gitkeep` | 项目目录占位 |
| trace-to-edm | `projects/default/` | 默认项目骨架（空目录） |
| trace-to-edm | `work/call_trace_to_edm*.py` | 工具脚本 |
| trace-engine-web | `work/README_PRODUCT.md` | 产品说明 |

### 10.3 清理验证

清理后应通过：
- `verify_portable.py` (14项)
- `portable_verify.py` (61项)
- `sync_check.py`（源码一致性）
- 三大WEB健康检查（`/api/health` 或 `/api/version`）

---

## 十一、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-08-02 | 初版：三大WEB MCP协议补齐（21工具），通过运作核查，便携目录同步，运行时记忆清理 |
