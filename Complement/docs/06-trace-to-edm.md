# trace-to-edm — 桥接服务

## 概述

连接 TRACE 因果发现与 EDM 动力学分析的桥接层。
将 TRACE 输出的概念矩阵转换为 EDM 可处理的 CSV 时间序列，
并自动触发 EDM 分析任务。

## 目录结构

```
trace-to-edm/
├── server.js                 # HTTP 服务（Node.js）
├── edm_trigger.py            # EDM 触发器（Python）
├── bridge.py                 # 桥接逻辑
├── config.py                 # 配置
├── csv_builder.py            # CSV 构建器
├── dataset_manager.py        # 数据集管理
├── project_manager.py        # 项目管理
├── work_scanner.py           # 工作扫描器
├── layer1_meta_scm.py        # 元数据 SCM 层
├── layer2_semantic.py        # 语义层
├── layer3_sacred.py          # 神圣文本层
├── package.json
├── requirements.txt
├── public/
│   ├── index.html            # 前端页面
│   ├── css/main.css
│   └── js/
│       ├── app.js            # 应用逻辑
│       ── logCockpit.js     # 日志 Cockpit
├── projects/                 # 项目数据
│   ├── _index.json           # 项目索引
│   ── default/
│       ├── dataset.json      # 数据集配置
│       └── narrative_meta_trajectories.csv
├── data/
│   ├── inputs/               # 输入数据
│   └── outputs/              # 输出数据
├── sacred_texts/             # 神圣文本
├── portable_start.bat        # 便携启动
├── portable_verify.py        # 便携验证
├── 启动隧道.bat / 启动隧道.ps1
└── tunnel.ps1                # Cloudflare 隧道
```

## 数据流

```
TRACE 输出（概念矩阵）
    │
    ├── layer1_meta_scm.py    元数据结构化
    ├── layer2_semantic.py    语义层转换
    └── layer3_sacred.py      神圣文本层处理
    │
    ▼
csv_builder.py                构建 CSV 时间序列
    │
    ▼
dataset_manager.py            数据集管理 + 导出
    │
    ▼
edm_trigger.py                触发 EDM 分析
    │
    ▼
edm-takens-web API            POST /api/analyze/jobs
    │
    ▼
结果回传 trace-to-edm 展示
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| POST | `/api/trigger-edm` | 触发 EDM 分析 |
| GET | `/api/projects` | 项目列表 |
| GET | `/api/projects/:id` | 项目详情 |
| POST | `/api/projects` | 创建项目 |
| GET | `/api/datasets` | 数据集列表 |

## 三层处理架构

### Layer 1: 元数据 SCM
- 结构化 TRACE 输出的概念矩阵
- 提取时间序列元数据
- 构建结构因果模型（SCM）框架

### Layer 2: 语义层
- 语义概念映射
- 变量关系推断
- 时间序列对齐

### Layer 3: 神圣文本层
- 特殊文本格式处理
- 叙事元数据提取
- 轨迹数据生成

## 启动

```bash
cd trace-to-edm
npm install          # 首次
node server.js
# 访问 http://localhost:3100
```

## 前端特性

- 实时日志 Cockpit（分级图标 + 过滤）
- 项目/数据集管理
- EDM 触发状态显示
- 特摄风格 UI
