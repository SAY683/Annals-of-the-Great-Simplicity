# Complement 项目整体说明书

> **Annals of the Great Simplicity — 因果分析工具链 + 神纪知识图谱**
> 版本：2026-10-18 | 维护状态：活跃

---

## 项目总览

本工具链由五个相互关联的因果分析项目 + 一个 GraphRAG 知识图谱成品组成：

```
┌─────────────────────────────────────────────────────────────────┐
│                     数据输入层                                    │
│  文本语料 / CSV 时间序列 / 叙事元数据                              │
└──────────────┬──────────────────────────────┬───────────────────
               │                              │
    ┌──────────▼──────────┐     ┌─────────────▼──────────────┐
    │   trace-engine      │     │     edm-takens             │
    │   (因果发现引擎)     │     │   (动力学分析引擎)          │
    │   Python CLI        │     │   Python CLI               │
    ──────────┬──────────┘     ─────────────┬──────────────┘
               │                              │
    ┌──────────▼──────────┐     ┌─────────────▼──────────────┐
    │   trace-to-edm      │────▶│     edm-takens-web         │
    │   (桥接层)           │     │   (Web 服务)               │
    │   Node.js + Python  │     │   FastAPI + Vite           │
    └──────────┬──────────┘     └────────────────────────────┘
               │
    ┌──────────▼──────────┐
    │   trace-engine-web  │
    │   (Web 服务)         │
    │   Node.js + Express     │
    └─────────────────────┘
```

> 另附 **GraphRAG-神纪图谱**：独立的 GraphRAG 知识图谱成品（《神纪》典籍，
> 开箱即用的 MCP 工具，非因果分析链路组成部分），见 [GraphRAG-神纪图谱](../GraphRAG-神纪图谱/README.md)。

## 五大因果分析项目 + GraphRAG

| # | 项目 | 类型 | 端口 | 技术栈 | 核心能力 |
|---|------|------|------|--------|----------|
| 1 | **edm-takens** | CLI 库 | — | Python | EDM + HAVOK + CCM 时间序列动力学分析 |
| 2 | **edm-takens-web** | Web 服务 | 8000 | FastAPI + Vite | edm-takens 的 Web 前端 |
| 3 | **trace-engine** | CLI 库 | — | Python | TRACE 因果发现 + 六战士诊断 + LLaMA 模型 |
| 4 | **trace-engine-web** | Web 服务 | 3000 | Node.js + Express | trace-engine 的 Web 前端 |
| 5 | **trace-to-edm** | 桥接服务 | 3100 | Node.js + Python | 将 TRACE 输出转为 EDM 输入，触发 EDM 分析 |
| 6 | **GraphRAG-神纪图谱** | 知识图谱 + MCP | — | Python GraphRAG + lancedb | 《神纪》典籍 Local/Global/Drift/Basic 问答，暴露为标准 MCP 工具 |

## 文档索引

| 文件 | 内容 |
|------|------|
| [01-architecture.md](01-architecture.md) | 系统架构、数据流、模块依赖关系 |
| [02-edm-takens.md](02-edm-takens.md) | edm-takens 核心库详细说明 |
| [03-edm-takens-web.md](03-edm-takens-web.md) | edm-takens-web Web 服务说明 |
| [04-trace-engine.md](04-trace-engine.md) | trace-engine 因果引擎说明 |
| [05-trace-engine-web.md](05-trace-engine-web.md) | trace-engine-web Web 服务说明 |
| [06-trace-to-edm.md](06-trace-to-edm.md) | trace-to-edm 桥接层说明 |
| [07-deployment.md](07-deployment.md) | 部署、隧道、便携目录维护 |
| [08-debugging.md](08-debugging.md) | 故障排查、常见问题、调试技巧 |
| [09-data-pipeline.md](09-data-pipeline.md) | 数据流转、文件格式、分析流程 |
| [10-models.md](10-models.md) | 模型位置、ModelScope 来源、大小校验 |
| [11-dependencies.md](11-dependencies.md) | Python/Node 依赖、解释器选择、锁文件 |
| [12-security.md](12-security.md) | 本地/隧道鉴权、API Key、网关边界 |
| [13-maintenance-debt.md](13-maintenance-debt.md) | P2 维护债务与后续顺序 |

## 研究论文

| 文件 | 内容 |
|------|------|
| [五大项目算法模型论文.md](<../TRACE Engine(EDM-Takens CCM)/研究汇报/五大项目算法模型论文.md>) | 6.7.0 系统论文：实现、真实微信公众号试点、测试与可复现性评估 |
| [五大项目算法模型论文-v1.4-历史.md](<../TRACE Engine(EDM-Takens CCM)/研究汇报/archive/五大项目算法模型论文-v1.4-历史.md>) | v1.4 历史算法叙事，仅作版本归档 |

## 快速开始

```powershell
# 1. 验证便携目录完整性
# 用 check_env 中标记为 [OK] 的解释器；本机 Windows 可直接用 py -3.13
cd "Complement"
py -3.13 tools\check_env.py
py -3.13 "TRACE Engine(EDM-Takens CCM)\verify_portable.py"
# 若缺依赖：powershell -File tools\bootstrap.ps1

# 2. 启动所有 Web 服务（默认仅本地）
.\start_all.bat
# 需要受保护的 Cloudflare 隧道时：
.\start_all.bat tunnel

# 3. 或单独启动各服务
cd "TRACE Engine(EDM-Takens CCM)\edm-takens-web"
python run_backend.py          # EDM Web → http://localhost:8000

cd "TRACE Engine(EDM-Takens CCM)\trace-engine-web"
powershell -File start.ps1     # TRACE Web → http://localhost:3000

cd "TRACE Engine(EDM-Takens CCM)\trace-to-edm"
node server.js                 # 桥接服务 → http://localhost:3100

# 4. GraphRAG 神纪知识图谱 (独立成品, 见 GraphRAG-神纪图谱/README.md)
cd "GraphRAG-神纪图谱"
.\scripts\00-start-embedding.bat   # 终端 1: 启动向量服务
.\scripts\01-start-mcp.bat         # 终端 2: 启动 MCP (保持窗口开启)
.\scripts\02-selfcheck-query.bat   # 终端 3: 自检 (结构化回答即链路正常)

# 5. 发布前清理运行残留与构建干净源码包
cd "Complement"
powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean_runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_release.ps1
```

## 目录结构


```
Complement/
├── Docs/                          # 本文档集
├── GraphRAG-神纪图谱/              # 项目 6: 神纪知识图谱 (GraphRAG + MCP)
│   ├── docs/                      # 技术文档 (架构/配置/数据/维护/扩展/合规)
│   ├── mcp/graphrag_mcp.py        # MCP 服务器 (免配置)
│   ├── project/                   # GraphRAG 项目根 (含已构建索引)
│   ├── scripts/                   # 一键启动/自检/重建/停止
│   └── visualization/             # graphml + 图谱全景/核心图
├── start_all.bat / start_all.ps1  # 统一启动脚本
└── TRACE Engine(EDM-Takens CCM)/
    ├── edm-takens/                # 项目 1: EDM 核心库
    ├── edm-takens-web/            # 项目 2: EDM Web 服务
    ├── trace-engine/              # 项目 3: TRACE 引擎
    ├── trace-engine-web/          # 项目 4: TRACE Web 服务
    ├── trace-to-edm/              # 项目 5: 桥接层
    ├── Models/                    # LLaMA 模型目录
    ├── verify_portable.py         # 便携目录验证
    └── sync_product.py            # 同步脚本
```
