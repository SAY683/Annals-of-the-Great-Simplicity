# 五大项目整体说明书

> **Annals of the Great Simplicity — 因果分析工具链**
> 版本：2026-07-21 | 维护状态：活跃

---

## 项目总览

本工具链由五个相互关联的项目组成，提供从**文本因果发现**到**时间序列动力学分析**的完整能力：

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
    │   Node.js + Koa     │
    └─────────────────────┘
```

## 五大项目

| # | 项目 | 类型 | 端口 | 技术栈 | 核心能力 |
|---|------|------|------|--------|----------|
| 1 | **edm-takens** | CLI 库 | — | Python | EDM + HAVOK + CCM 时间序列动力学分析 |
| 2 | **edm-takens-web** | Web 服务 | 8000 | FastAPI + Vite | edm-takens 的 Web 前端 |
| 3 | **trace-engine** | CLI 库 | — | Python | TRACE 因果发现 + 六战士诊断 + LLaMA 模型 |
| 4 | **trace-engine-web** | Web 服务 | 3000 | Node.js + Koa | trace-engine 的 Web 前端 |
| 5 | **trace-to-edm** | 桥接服务 | 3100 | Node.js + Python | 将 TRACE 输出转为 EDM 输入，触发 EDM 分析 |

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

## 快速开始

```powershell
# 1. 验证便携目录完整性
cd "Complement"
python "TRACE Engine(EDM-Takens CCM)\verify_portable.py"

# 2. 启动所有 Web 服务 + 隧道
.\start_all.bat

# 3. 或单独启动各服务
cd "Skill\edm-takens-web"
python run_backend.py          # EDM Web → http://localhost:8000

cd "TRACE Engine(EDM-Takens CCM)\trace-engine-web"
powershell -File start.ps1     # TRACE Web → http://localhost:3000

cd "TRACE Engine(EDM-Takens CCM)\trace-to-edm"
node server.js                 # 桥接服务 → http://localhost:3100
```

## 目录结构

```
Complement/
── docs/                          # 本文档集
── start_all.bat / start_all.ps1  # 统一启动脚本
├── Skill/
│   ├── edm-takens/                # 项目 1: EDM 核心库
│   └── edm-takens-web/            # 项目 2: EDM Web 服务
└── TRACE Engine(EDM-Takens CCM)/
    ├── trace-engine/              # 项目 3: TRACE 引擎
    ├── trace-engine-web/          # 项目 4: TRACE Web 服务
    ├── trace-to-edm/              # 项目 5: 桥接层
    ├── Models/                    # LLaMA 模型目录
    ├── verify_portable.py         # 便携目录验证
    └── sync_product.py            # 同步脚本
```
