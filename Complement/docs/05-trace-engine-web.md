# trace-engine-web — TRACE Web 服务

## 概述

基于 Node.js (Koa) 的 Web 前端，提供 TRACE 因果分析的图形界面。
支持三种分析模式（LIGHT/DEEP/SUPER），通过 SSE 实时推送日志。

## 目录结构

```
trace-engine-web/
├── server.js                 # HTTP + SSE 服务端（Koa）
├── start.bat / start.ps1     # 启动脚本
├── stop_servers.bat / stop_servers.ps1  # 停止脚本
├── py_bridge.py              # Python 子进程桥接
├── llama_worker.py           # LLaMA 模型常驻 Worker
├── package.json
├── routes/
│   ├── analysis.js           # 分析路由
│   ├── jobs.js               # 任务管理
│   ├── admin.js              # 管理路由
│   └── system.js             # 系统路由
├── services/
│   ├── analysis.js           # 分析服务
│   └── llamaWorker.js        # LLaMA Worker 管理
├── middleware/
│   ├── auth.js               # 认证中间件
│   └── index.js              # 中间件注册
├── lib/
│   ├── state.js              # 状态管理
│   └── utils.js              # 工具函数
── schema/
│   ├── bridge_schema.json    # 桥接 Schema
│   ── result_schema.json    # 结果 Schema
├── public/
│   ├── index.html            # 前端页面
│   ├── css/
│   │   ├── main.css          # 主样式
│   │   └── theme.css         # 特摄主题
│   └── js/
│       ├── app.js            # 应用主逻辑
│       ├── jobs.js           # 任务管理
│       ├── render.js         # 渲染引擎
│       ├── schema.js         # Schema 渲染
│       └── sse.js            # SSE 客户端
├── work/                     # 工作目录（运行时生成）
├── tunnel_logs/              # 隧道日志
└── 启动隧道.bat              # Cloudflare 隧道
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/analyze` | 提交分析任务 |
| GET | `/api/jobs` | 任务列表 |
| GET | `/api/jobs/:id` | 任务详情 |
| GET | `/api/jobs/:id/log` | SSE 实时日志 |
| POST | `/api/retry/:id` | 重试任务（不支持 SUPER） |
| GET | `/api/config` | 配置信息（含 bridgeParamSchema） |
| GET | `/api/presets` | 参数预设 |
| GET | `/api/schema` | Schema 定义 |
| GET | `/api/health` | 健康检查 |

## 进程架构

```
──────────────┐     ┌──────────────┐
│  server.js   │────▶│  py_bridge.py │──▶ trace-engine CLI
│  (Koa :3000) │     │  (subprocess) │
└──────────────┘     └──────────────┘
                            │
                     ┌──────▼──────┐
                     │llama_worker.py│──▶ LLaMA 模型
                     │  (常驻进程)   │
                     └─────────────┘
```

## SUPER 模式实现

- **速率预估**：processed_pairs/total_pairs、rate(pairs/s)
- **主动停止**：基于剩余时间估计的主动取消机制
- **VRAM 检查**：469M+ 模型建议 >= 3.0GB 显存
- **超时保护**：24 小时安全兜底
- **SSE 心跳**：30 秒注释心跳防止代理断开

## 启动

```bash
cd trace-engine-web
npm install          # 首次
powershell -File start.ps1
# 访问 http://localhost:3000
```

## 前端特性

- 特摄风格 UI（暗色主题 + CRT 扫描线）
- 顶部状态看板（MODE + CORE 显示）
- 右上角任务时钟
- SUPER 模式橙色脉冲边框
- 统一面板图标系统
- 实时日志 Cockpit（分级图标 + 过滤工具栏）
