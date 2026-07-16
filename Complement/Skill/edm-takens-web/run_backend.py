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
os.chdir(_PROJECT_ROOT)

if __name__ == "__main__":
    # Ensure runtime directories exist
    os.makedirs(os.path.join(_PROJECT_ROOT, "data"), exist_ok=True)
    os.makedirs(os.path.join(_PROJECT_ROOT, "results"), exist_ok=True)

    uvicorn.run(
        "api:app",
        app_dir="backend",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
