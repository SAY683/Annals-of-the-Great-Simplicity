# edm-takens-web — EDM Web 服务

## 概述

基于 FastAPI + Vite 的 Web 前端，提供 EDM 动力学分析的图形界面。

## 目录结构

```
edm-takens-web/
├── backend/
│   ├── api.py                  # FastAPI 应用入口
│   ├── job_store.py            # SQLite 任务持久化
│   ├── core/
│   │   ├── locks.py            # 并发锁 + 目录初始化
│   │   └── runtime.py          # 运行时配置
│   ├── edmtakens/              # edm-takens/src/ 的副本
│   ├── routes/
│   │   ├── analyze.py          # POST /api/analyze/jobs
│   │   ├── datasets.py         # 数据集管理
│   │   └── history.py          # GET /api/history
│   ├── services/
│   │   ├── file_management.py  # 文件上传/迁移
│   │   └── summary_builder.py  # 结果摘要构建
│   ├── workers/
│   │   └── analysis_worker.py  # 后台任务执行
│   └── sync_check.py           # 副本同步检查
── frontend/
│   ├── index.html
│   ├── src/
│   │   ├── main.js             # 前端主逻辑
│   │   └── style.css           # 样式（特摄风格）
│   ├── package.json
│   └── vite.config.js
── data/                       # 示例数据
├── results/                    # 分析结果（运行时生成）
├── run_backend.py              # 启动脚本
├── requirements.txt
── 启动隧道.bat                 # Cloudflare 隧道
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/analyze/jobs` | 提交 EDM 分析任务 |
| GET | `/api/analyze/jobs/{job_id}` | 查询任务状态/日志/结果 |
| GET | `/api/history` | 历史任务列表 |
| GET | `/api/health` | 健康检查 |

## 任务执行流程

```
1. 用户上传 CSV → POST /api/analyze/jobs
2. _prepare_pipeline_data() → 数据预处理
3. _make_config() → 构建 PipelineConfig
4. run_full_analysis() → 三阶段分析
   ├── Stage 1: run_pipeline() (EDM + HAVOK)
   ├── Stage 2: run_enhanced_validation() (交叉验证)
   └── Stage 3: interpret_game_data() (最终解释)
5. _move_results_to_task() → 迁移结果文件
6. _build_summary() → 构建摘要
7. job.finish(result=...) → 完成
```

## 并发控制

- `_ANALYSIS_LOCK` — 分析任务互斥锁（最多 1 个并发）
- `_STDOUT_LOCK` — stdout 重定向锁
- `_MOVE_LOCK` — 文件迁移锁

## 副本同步

`edmtakens/` 是 `edm-takens/src/` 的副本，通过 `sync_check.py` 验证一致性。

预期差异（白名单）：
- `_paths.py` — 支持 `EDMTAKENS_DATA_DIR` 环境变量
- `__init__.py` — 包说明注释不同
- `enhanced_cross_validate.py` — Web 专用路径适配
- `environment_check.py` — Web 专用路径检查

## 启动

```bash
cd edm-takens-web
pip install -r requirements.txt
python run_backend.py
# 访问 http://localhost:8000
```

## 前端特性

- 特摄风格 UI（暗色主题 + CRT 扫描线）
- SSE 实时日志流（30 秒心跳）
- 任务队列管理
- 结果可视化（PNG 图表）
