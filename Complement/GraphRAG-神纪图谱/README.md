# GraphRAG · 神纪知识图谱（便携归档版）

> 《神纪》系列神学典籍的 **GraphRAG 知识图谱成品**。索引已构建完毕（500/500 社区报告），
> 开箱即用：启动依赖服务 → 连接 MCP → 直接问答。

## 一、这是什么

把《神纪》合并版（`project\input\神纪_合并版.md`，约 24 万字符）通过 GraphRAG 管线构建为知识图谱，
支持 **Local / Global / Drift / Basic** 四种检索问答（抽象神学题可开 **解经模式** `decode=true`，把密语翻成平白话，见 `docs\示例-信念问答.md`），并暴露为标准 **MCP 工具**，
任何支持 MCP 的 AI 宿主（Codex / Claude / Cursor 等）都可调用。

**图谱规模**（本归档已含成品索引）：

| 指标 | 数值 |
|---|---|
| 实体 | 3,709（2,394 个有关联） |
| 关系 | 4,773 |
| 社区 / 社区报告 | 500 / 500 |
| 文本块 | 119 |
| 向量库 | 3 个（entity_description / community_full_content / text_unit_text，1024 维） |
| 构建成本 | ~$5.25（经 CC Switch 代理路由到**官方 DeepSeek**，~493 万 tokens；原记\"0 元 opencode\"有误，见归档） |

## 二、目录结构

```
GraphRAG-神纪图谱\
├── README.md                  ← 本文件（快速开始）
├── docs\                      ← 技术文档（编号）
│   ├── 01-架构与工作原理.md
│   ├── 02-配置详解.md
│   ├── 03-数据与索引.md
│   ├── 04-维护与故障排查.md
│   ├── 05-扩展与自定义.md
│   ├── 06-责任与合规.md
│   └── MCP_API_REFERENCE.md
├── project\                   ← GraphRAG 项目根（便携核心）
│   ├── settings.yaml          ← 模型 / 向量 / 管线配置
│   ├── prompts\               ← 全部提示词（可修改）
│   ├── input\神纪_合并版.md    ← 源文本
│   └── output\                ← 已构建索引（parquet + lancedb + graphml）
├── mcp\
│   └── graphrag_mcp.py        ← MCP 服务器（脚本相对路径，免配置）
├── scripts\                   ← 一键启动/自检/重建/重打补丁/停止（含 common.ps1 共享助手）
├── visualization\             ← graphml + 全景/核心 PNG
└── 图谱项目训练经验归档.md      ← 完整踩坑与经验
```

## 三、快速开始（开箱即用）

前置依赖（本机已具备，换机器需安装）：
- Python 3.10+ 且已安装 `graphrag` 包（本归档在 `G:\Python` 环境构建）
- **CC Switch** 运行中，且已登录 **opencode Go**（提供 LLM，端口 127.0.0.1:15721）
- `llama-server` + bge-m3 GGUF（提供本地向量，见脚本默认路径）

步骤：

1. **启动向量服务**（终端 1）：双击 `scripts\00-start-embedding.bat`
2. **启动 MCP**（终端 2）：双击 `scripts\01-start-mcp.bat`（保持窗口开启）
3. **自检**（终端 3）：双击 `scripts\02-selfcheck-query.bat`，看到结构化回答即链路正常
4. 在支持 MCP 的宿主中把 `mcp\graphrag_mcp.py` 注册为 MCP 服务器，即可调用
   `graphrag_query` / `graphrag_list_projects` / `graphrag_get_context`

> 若移动整个文件夹：**无需改任何配置**——MCP 与脚本均按自身位置解析 `project\`。
> 唯一可能需调整的是 `scripts` 中 llama-server / 模型 / Python 的默认路径（可用环境变量覆盖）。

> **脚本可配置环境变量**（全部有默认值，换机器时按需设置）：
> `GRAPHRAG_PYTHON`（Python 路径）、`LLAMA_SERVER` / `BGE_MODEL` / `EMBED_PORT`（向量服务）、
> `EMBED_WAIT_SECONDS`（加载等待秒数，默认 90）。Python 会自动探测能 `import graphrag` 的解释器。
## 四、依赖清单

| 组件 | 用途 | 位置/来源 |
|---|---|---|
| graphrag (Python) | 索引与查询引擎 | G:\Python（pip install graphrag） |
| llama-server | 本地向量（bge-m3） | G:\AI\llama-cpp\llama-server.exe |
| bge-m3 FP16 GGUF | 嵌入模型（1024 维） | G:\AI\轻量大模型\bge-m3\bge-m3-FP16.gguf |
| CC Switch | opencode Go 网关（LLM） | G:\AI\CC-Switch（127.0.0.1:15721） |
| opencode Go | 订阅制 LLM（deepseek-v4-flash） | 网页订阅 + API key |

## 五、常见问题速查（详见 docs\04）

- 查询报错"没有 output 目录" → 检查 `GRAPHRAG_PROJECT` 是否被设成错误路径，或直接传 `project=` 参数
- MCP 返回乱码路径 → 本归档路径全 ASCII，天然免疫；工作副本已加多候选路径容错
- 查询超时 → 确认 CC Switch 运行中（端口 15721）且 embedding 服务在线（8081）
- 想换模型 / 调实体类型 → 见 `docs\02-配置详解.md` 与 `docs\05-扩展与自定义.md`

- 想理解"通用问法 vs 语料词汇问法"的差异 → `docs\示例-信念问答.md`（global 对照 + drift 主答）
## 六、文档导航

- 想理解它是怎么工作的 → `docs\01-架构与工作原理.md`
- 想改配置 → `docs\02-配置详解.md`
- 想了解数据内容与质量 → `docs\03-数据与索引.md`
- 出问题怎么办 → `docs\04-维护与故障排查.md`
- 想扩展/自定义 → `docs\05-扩展与自定义.md`
- 使用边界与责任 → `docs\06-责任与合规.md`
- MCP 接口细节 → `docs\MCP_API_REFERENCE.md`
- 完整经验（含踩坑）→ `图谱项目训练经验归档.md`



