#!/usr/bin/env python3
"""
EDM-Takens Web Backend entry point.

Usage:
  pip install -r requirements.txt
  python run_backend.py

Then open http://localhost:8000 in a browser (or use the Vite dev server
on port 5173 which proxies API calls to this backend).
"""
import os
import sys
import tempfile
import uvicorn

# R49 fix: 防止后端启动时生成 __pycache__ 污染便携目录
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# debt-17: 使用 append 而非 insert(0)，确保已通过 `pip install -e .`
# 安装的可编辑包具有更高导入优先级。副本目录仅作为回退。
sys.path.append(os.path.join(_PROJECT_ROOT, "backend", "edmtakens"))

# debt-22: 环境变量从 pipeline.py 移至此入口点，确保在 numpy/matplotlib
# 导入前生效。库模块不应在导入时设置进程级环境变量。
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MPLCONFIGDIR'] = os.path.join(tempfile.gettempdir(), 'edm_takens_mpl')
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

# debt-22: os.chdir 从 api.py 移至此入口点。pipeline 内部硬编码了相对
# 路径 results/，必须在进程启动时统一 cwd。原先在 api.py 模块加载时
# chdir 会产生导入副作用，且直接 `uvicorn api:app` 时行为不一致。
# E2E 冒烟隔离 (smoke_e2e.py): EDMTAKENS_WORKDIR 覆盖工作目录, 使 pipeline
# 的相对 results/ 写入落入临时目录而非便携目录. 默认仍为项目根.
_EDM_WORKDIR = os.environ.get("EDMTAKENS_WORKDIR", _PROJECT_ROOT)
os.chdir(_EDM_WORKDIR)

if __name__ == "__main__":
    # Ensure runtime directories exist
    _data_dir = os.environ.get("EDMTAKENS_DATA_DIR", os.path.join(_PROJECT_ROOT, "data"))
    _results_dir = os.environ.get("EDMTAKENS_RESULTS_DIR", os.path.join(_PROJECT_ROOT, "results"))
    os.makedirs(_data_dir, exist_ok=True)
    os.makedirs(_results_dir, exist_ok=True)

    uvicorn.run(
        "api:app",
        # ROUND51 E2E 修复: app_dir 用绝对路径, 而非相对 "backend".
        # EDMTAKENS_WORKDIR 覆盖时 cwd 变为临时目录, 相对 app_dir 会
        # 找不到 backend/api.py → "Could not import module api".
        app_dir=os.path.join(_PROJECT_ROOT, "backend"),
        host="127.0.0.1",  # Q9 P1-23 修复：仅绑定本地回环，避免暴露到所有网络接口
        port=int(os.environ.get("EDM_PORT", "8000")),  # EDM_PORT 覆盖 (README 已文档化, 此前未实现)
        reload=False,
    )
