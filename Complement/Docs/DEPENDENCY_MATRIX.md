# 五大项目依赖矩阵

> 创建: 2026-07-27 (Round 20)
> 维护: 每次依赖变更后同步更新
> 目标: 提供五大项目完整的依赖图谱，支持可维护、可复制、可理解的部署
> 补全: 2026-08-03 (Round 41) — 原 v1 在 ASCII 图第 17 行被截断，本次按实际项目结构重写

---

## 1. 依赖总览

```
┌────────────────────────────────────────────────────────────────────┐
│                    五大项目依赖拓扑图                                │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  edm-takens (Python CLI)                                           │
│    └─ 依赖: numpy, scipy, pandas, scikit-learn                     │
│    └─ 被: edm-takens-web, trace-to-edm 调用                        │
│                                                                    │
│  edm-takens-web (FastAPI + Vite)                                   │
│    └─ 依赖: edm-takens (核心库), fastapi, uvicorn                   │
│    └─ 端口: 8000 (EDM_PORT 可覆盖)                                  │
│    └─ 绑定: 127.0.0.1                                              │
│                                                                    │
│  trace-engine (Python CLI)                                         │
│    └─ 依赖: numpy, pandas, dowhy, causal-learn, transformers       │
│    └─ SUPER 模式依赖: Models/ (Qwen2.5, shehui-llama, shenji-llama) │
│    └─ 被: trace-engine-web, trace-to-edm 调用                      │
│                                                                    │
│  trace-engine-web (Node.js + Koa)                                  │
│    └─ 依赖: trace-engine (Python via py_bridge), koa, vite          │
│    └─ 端口: 3000 (PORT 可覆盖)                                      │
│    └─ 绑定: 127.0.0.1                                              │
│                                                                    │
│  trace-to-edm (Node.js + Python)                                   │
│    └─ 依赖: trace-engine (因果提取), edm-takens-web (EDM 触发)       │
│    └─ 端口: 3100 (TRACE_TO_EDM_PORT 可覆盖)                        │
│    └─ 绑定: 127.0.0.1                                              │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. Python 依赖矩阵

### 2.1 edm-takens (核心库)

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| numpy | >=2.0 | 数值计算核心 |
| scipy | >=1.10 | SVD/PCA/统计检验 |
| pandas | >=2.0 | DataFrame 数据结构 |
| scikit-learn | >=1.3 | PCA、回归、邻近搜索 |

### 2.2 edm-takens-web (Web 服务)

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| fastapi | >=0.100 | Web 框架 |
| uvicorn | >=0.23 | ASGI 服务器 |
| edm-takens | 本地 | 核心分析库（相对路径导入）|

### 2.3 trace-engine (核心库)

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| numpy | >=2.0 | 数值计算 |
| pandas | >=2.0 | 数据处理 |
| dowhy | >=0.14 | 因果推断（六战士之一）|
| causal-learn | >=0.1.3 | PC/GES 因果发现（六战士之一）|
| transformers | >=4.30 | SUPER 模式 LLaMA 推理 |
| torch | >=2.0 | LLaMA 模型后端 |

### 2.4 trace-engine-web (Web 服务)

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| koa | >=2.14 | Web 框架 |
| vite | >=5.0 | 前端构建 |
| trace-engine | 本地 | 通过 py_bridge.py 调用 |

### 2.5 trace-to-edm (桥接服务)

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| express | >=4.18 | Web 框架 |
| trace-engine | 本地 | L1 因果提取 |
| edm-takens-web | HTTP | 通过 HTTP 触发 EDM 分析 |

---

## 3. 跨项目调用关系

```
trace-engine-web ──HTTP──> trace-engine (py_bridge.py)
        │
        └──HTTP──> trace-to-edm ──HTTP──> edm-takens-web ──import──> edm-takens
```

| 调用方 | 被调用方 | 协议 | 端点 |
|--------|----------|------|------|
| trace-engine-web | trace-engine | 子进程 (Python) | py_bridge.py |
| trace-engine-web | trace-to-edm | HTTP | http://127.0.0.1:3100/api/run |
| trace-to-edm | trace-engine | Python import | counterfactual_bridge.py |
| trace-to-edm | edm-takens-web | HTTP | http://127.0.0.1:8000/api/run |
| edm-takens-web | edm-takens | Python import | edm-takens/src/ |

---

## 4. 共享资源

| 资源 | 位置 | 消费方 |
|------|------|--------|
| auth_middleware.js | shared/ | trace-to-edm, edm-takens-web |
| tokusatsu.css | shared/themes/ | 全部 Web 项目前端 |
| Models/ | 成品根 Models/ | trace-engine (SUPER 模式) |

---

## 5. 便携目录布局

```
TRACE Engine(EDM-Takens CCM)/       <- 便携成品根
├── edm-takens/                      <- 核心库
├── edm-takens-web/                  <- Web 服务 (端口 8000)
├── trace-engine/                    <- 核心库
├── trace-engine-web/                <- Web 服务 (端口 3000)
├── trace-to-edm/                    <- 桥接服务 (端口 3100)
├── shared/                          <- 共享资源
├── Models/                          <- LLaMA 模型 (SUPER 模式)
├── 研究汇报/                         <- 论文 + 最近2轮元反思 + 审计报告
├── verify_portable.py               <- 14 项便携验证
├── sync_product.py                  <- 同步脚本
├── README.md                        <- 便携目录说明
├── PORTABLE_TECHNICAL_GUIDE.md      <- 便携技术指南
├── test_mcp_protocol.py             <- MCP 协议测试
└── test_cross_project_http.py       <- 跨项目 HTTP 测试
```

> **注**: META_THINKING/ 完整归档仅保留在工作目录 `f:\攻略\研发测试\Docs\META_THINKING/`，
> 成品目录仅通过 `研究汇报/` 文件夹携带最近2轮元反思，避免冗余。

---

## 6. 启动顺序

正确启动顺序（按依赖关系）：

1. `edm-takens-web` (端口 8000) — EDM 分析服务
2. `trace-engine-web` (端口 3000) — TRACE 因果发现服务
3. `trace-to-edm` (端口 3100) — 桥接服务（依赖前两者）

每个项目都有独立的 `start.bat` / `start_mvp.bat`，使用相对路径，开箱即用。
