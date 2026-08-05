# MCP_API_REFERENCE · GraphRAG MCP 工具接口

## 概览

`mcp\graphrag_mcp.py` 是一个标准 **MCP (Model Context Protocol) server**（stdio 传输）。
注册到任何 MCP 宿主后，宿主可调用以下工具查询《神纪》知识图谱。

## 工具 1：graphrag_query

**用途**：对已索引文档库执行 GraphRAG 检索问答。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| question | str | 是 | — | 问题（任意语言，如"什么是爱"） |
| method | str | 否 | local | local / global / drift / basic |
| community_level | int | 否 | 2 | global 搜索的 Leiden 层级（越大社区越小） |
| decode | bool | 否 | false | 解经模式：把密语/隐喻翻译成平白概念、区分字面与象征、给出可操作结论（避免"念经式"复读） |
| project | str | 否 | 自动 | 项目根目录；缺省自动探测 |

**返回**（JSON 字符串）：
```json
{ "ok": true, "method": "global", "question": "…", "answer": "…", "error": null }
```
`answer` 为 Markdown 文本，带 `[Data: Reports (…)]` 引用。

**示例**（MCP 调用语义）：
```
graphrag_query(question="神姬是谁？", method="global")
graphrag_query(question="什么是觉悟？", method="drift")
graphrag_query(question="我应该相信什么？", method="drift", decode=true)  // 解经模式
graphrag_query(question="种子在书中象征什么？", method="local")
```

## 工具 2：graphrag_list_projects

**用途**：列出可用索引项目及统计。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| project | str | 否 | 自动 | 项目根目录 |

**返回**（JSON）：
```json
{ "project": "…", "exists": true, "entities": 3038, "relationships": 3987,
  "communities": 555, "entity_types": { "CONCEPT": 1712, … } }
```

## 工具 3：graphrag_get_context

**用途**：获取某实体的图谱上下文（邻居/关系/社区）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| entity | str | 是 | — | 实体名，如 "爱"、"玄姬" |
| project | str | 否 | 自动 | 项目根目录 |

**返回**：JSON，含实体信息、邻居、关系描述。

## 项目路径解析规则（可移植性）

1. 显式 `project=` 参数优先
2. 其次 `$GRAPHRAG_PROJECT` 环境变量
3. 再次脚本内置默认
4. 最后脚本相对路径候选（`<归档>/project`）——本归档即用此规则，移动文件夹无需改配置

## 注册方法（以 Codex 为例）

```bash
codex mcp add graphrag -- python <归档路径>\mcp\graphrag_mcp.py
# 或图形界面添加 MCP server，命令指向该脚本
```
启动 MCP 前先运行 `scripts\00-start-embedding.bat` 与 `scripts\01-start-mcp.bat`。

## 错误处理约定

- 所有工具**不抛异常**，而是返回 `{"ok": false, "error": "…"}`（list/get_context 类似）。
- 常见错误与处理见 `04-维护与故障排查.md`。
- 查询超时阈值 1800s（长时间大图 global 搜索）。
---

## 标准协议验证（2026-08-05 · 官方 mcp SDK 客户端实测）

用 `mcp` Python SDK（2.0.0）的 `stdio_client` + `ClientSession` 对 `mcp\graphrag_mcp.py` 做完整协议级测试，全部通过：

| 步骤 | 结果 |
|---|---|
| initialize（握手） | ✅ server=graphrag 1.0.0，protocol 2025-11-25 |
| tools/list（工具枚举） | ✅ 3 个工具，JSON Schema 合法（question 必填等） |
| tools/call（调用） | ✅ 52s 返回结构化内容，isError=null |
| 中文往返 | ✅ 问题/实体中文经 stdio 零丢失 |
| 错误处理 | ✅ 不崩溃，返回 `{ok:false,error}` |

**三工具实测**：
- `graphrag_query(question="我当前应该怎么做？无关于目标，只是我应该遵循何种策略。", method="global")` → 完整策略综合回答（见 `示例-策略问答.md`）
- `graphrag_get_context(entity="爱")` → CONCEPT，degree 44，邻居/关系齐全
- `graphrag_list_projects() → 3038/3987/555 全量统计（2026-08-05 19:00 最终重建后实测）

**通用性要点**：
1. 传输层：服务端与客户端均由 mcp SDK 以 **UTF-8** 包装 stdio（`encoding="utf-8"`），中文安全。
2. 任何支持 MCP 的宿主（Codex/Claude/Cursor/n8n 等）均可用同样三步（initialize→list→call）接入。
3. 返回统一 JSON 字符串（text content），宿主可自行 `json.loads` 结构化处理。
4. 若某个宿主传入非 UTF-8 参数，服务端 `errors="replace"` 兜底，不会崩溃。
