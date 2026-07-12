"""
Counterfactual Sentai — 统一日志系统
======================================
用于 CLI 运行时的诊断日志记录。
日志写入 outputs/logs/ 目录（工作副本和便携副本均可用）。
"""

import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime


def setup_logging(log_dir: Path, name: str = "sentai") -> logging.Logger:
    """
    配置日志系统，输出到文件和控制台。

    Parameters
    ----------
    log_dir : Path
        日志目录（通常为 outputs/logs/）
    name : str
        日志器名称

    Returns
    -------
    logging.Logger
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{name}_{timestamp}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 清除旧 handler
    logger.handlers.clear()

    # 文件 handler — 完整记录
    fh = logging.FileHandler(str(log_file), encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)-7s] %(message)s',
        datefmt='%H:%M:%S'
    ))
    logger.addHandler(fh)

    # 控制台 handler — 仅 INFO+
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('  %(message)s'))
    logger.addHandler(ch)

    logger.info(f"Log: {log_file}")
    logger.info(f"Time: {datetime.now().isoformat()}")
    logger.info(f"Python: {sys.version.split()[0]}")

    return logger


def log_env_info(logger: logging.Logger):
    """记录环境信息到日志"""
    import platform
    logger.info(f"OS: {platform.system()} {platform.release()}")
    logger.info(f"CPU: {os.cpu_count()} cores")

    for mod, name in [('numpy', 'NumPy'), ('torch', 'PyTorch'),
                       ('dowhy', 'DoWhy'), ('causallearn', 'causal-learn'),
                       ('matplotlib', 'Matplotlib')]:
        try:
            m = __import__(mod)
            ver = getattr(m, '__version__', '?')
            logger.info(f"{name}: {ver}")
        except ImportError:
            logger.info(f"{name}: NOT INSTALLED")
