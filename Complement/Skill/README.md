# EDM-Takens Skill 便携目录

本目录包含两个子项目：

- **edm-takens/**：EDM-Takens 因果分析核心库（Python）
- **edm-takens-web/**：EDM-Takens Web MVP（FastAPI + Vite）

## 环境要求

- Python 3.11+
- Node.js 18+（仅 edm-takens-web 前端开发时需要）

## 快速开始

### edm-takens（命令行）

cd edm-takens
pip install -r requirements.txt
python run_pipeline.py --help

### edm-takens-web（Web 服务）

cd edm-takens-web
pip install -r requirements.txt
python run_backend.py

浏览器访问 http://localhost:8000

## 架构概览

### edm-takens
- src/ 下 19 个模块，含 _usability.py 统一可用性判定
- pyproject.toml 支持 editable install（pip install -e .）
- edm_auditor.py 5 档 verdict（PASS/PASS_WITH_NOTES/WARN/FAIL/BLOCKED）+ INCONCLUSIVE
- sovereign_havok.py degenerate 短路保护

### edm-takens-web
- api.py 模块化拆分（core/routes/services/workers）
- 副本同步：sync_check.py 校验 edmtakens/ 与 edm-takens/src/ 一致性
- data_quality.py 复用 _usability.py 避免阈值漂移

## 维护说明
- 副本同步：修改 edm-takens/src/ 后，运行 edm-takens-web/backend/sync_check.py 验证
- 环境变量：通过 run_backend.py / run_pipeline.py 设置，不在代码中硬编码
