# 系统架构与数据流

## 1. 整体架构

```
                    ┌─────────────────────┐
                    │    用户 / 浏览器      │
                    └──────┬──────┬───────┘
                           │      │
              ┌────────────▼─┐  ┌─▼──────────────┐
              │ trace-engine- │  │  edm-takens-   │
              │   web :3000   │  │    web :8000   │
              │  (Node+Express)   │  │  (FastAPI)     │
              └──────┬────────┘  └───────┬────────┘
                     │                    │
              ┌──────▼────────┐    ┌─────▼──────────┐
              │  trace-engine  │    │  edm-takens    │
              │  (Python CLI)  │    │  (Python CLI)  │
              ──────┬────────┘    └────────────────┘
                     │
              ┌──────▼────────┐
              │  trace-to-edm  │
              │   :3100        │
              │  (Node+Python) │
              └──────────────┘
                     │
              ┌──────▼────────┐
              │  edm-takens-   │
              │    web :8000   │
              │  (HTTP API)    │
              └───────────────┘
```

## 2. 数据流

### 路径 A：纯时间序列分析（不经过 TRACE）
```
CSV 文件 → edm-takens-web 上传 → EDM 分析 → 结果展示
```

### 路径 B：文本因果分析（完整链路）
```
文本输入 → trace-engine-web 上传
         → trace-engine (TRACE 概念提取 + 六战士诊断)
         → trace-to-edm (桥接：概念矩阵 → CSV)
         → edm-takens-web (EDM 分析)
         → 结果返回 trace-to-edm 展示
```

### 路径 C：SUPER 模式（LLaMA 模型）
```
文本输入 → trace-engine-web
         → LLaMA Worker (常驻进程，加载 shehui/shenji 模型)
         → token-level TRACE 因果发现
         → 六战士诊断 → 结果展示
```

## 3. 模块依赖关系

```
edm-takens/src/          (核心算法库，21 个模块)
    ├── sovereign_havok.py     HAVOK 分解
    ├── ccm_causality.py       CCM 因果检验
    ├── pipeline.py            管线编排
    ├── enhanced_cross_validate.py  交叉验证
    ├── final_interpretation.py     最终解释
    └── ...

edm-takens-web/backend/
    ├── edmtakens/           (edm-takens/src/ 的副本)
    ├── routes/              (HTTP 路由)
    ├── services/            (文件管理、摘要构建)
    ├── workers/             (后台任务执行)
    └── core/                (锁、运行时)

trace-engine/examples/counterfactual_hybrid/
    ├── six_warriors.py      六战士诊断
    ├── counterfactual_bridge.py  TRACE→DoWhy 桥接
    ├── dowhy_adapter.py     DoWhy 1.4 适配
    ├── presets.yaml         参数预设
    └── run_cli.py           CLI 入口

trace-engine-web/
    ├── server.js            HTTP + SSE 服务
    ├── py_bridge.py         Python 子进程桥接
    ├── llama_worker.py      LLaMA 模型 Worker
    └── services/            分析服务

trace-to-edm/
    ├── server.js            进程入口
    ├── src/app.js           Express 组装
    ├── src/routes/          按业务域拆分的路由
    ├── src/services/        Python/任务/数据集/轨迹服务
    ├── edm_trigger.py       EDM 触发器
    ├── layer1_meta_scm.py   元数据 SCM
    ├── layer2_semantic.py   语义层
    ├── layer3_sacred.py     神圣文本层
    └── bridge.py            桥接逻辑
```

## 4. 端口分配

| 服务 | 默认端口 | 回退范围 | 协议 |
|------|----------|----------|------|
| trace-engine-web | 3000 | 3000-3020 | HTTP + SSE |
| trace-to-edm | 3100 | 3100-3120 | HTTP |
| edm-takens-web | 8000 | 固定 | HTTP + SSE |

## 5. 源码与同步关系

本仓库是唯一可维护源码树，不依赖仓库外的开发目录或 `.skills` 镜像：

```
Complement/
├── shared/                        共享启动与解释器探测
├── tools/                         安装、审计、清理与发布工具
├── Docs/                          项目文档
└── TRACE Engine(EDM-Takens CCM)/
    ├── edm-takens/                算法唯一真源
    ├── edm-takens-web/            Web 服务；直接导入 edm-takens/src
    ├── trace-engine/              因果发现引擎
    ├── trace-engine-web/          引擎 Web 服务
    └── trace-to-edm/              桥接服务
```

`edm-takens-web/backend/sync_check.py` 负责确认 Web 端没有重新引入
`backend/edmtakens/` 算法副本，而不是与另一个外部“源目录”比对。`sync_product.py`
只用于显式构建另一个便携镜像，不是日常启动、升级或发布前置步骤。
