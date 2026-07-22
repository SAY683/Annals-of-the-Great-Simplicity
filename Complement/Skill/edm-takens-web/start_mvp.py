#!/usr/bin/env python3
"""
EDM-Takens Web MVP — 一键启动脚本

同时启动 Python FastAPI 后端与 Vite 前端开发服务器，
按 Ctrl+C 可一次性终止两个进程。
"""
import os
import sys
import time
import shutil
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_FRONTEND_DIR = os.path.join(_PROJECT_ROOT, "frontend")
_BACKEND_CMD = [sys.executable, "run_backend.py"]
_NPM = shutil.which("npm") or "npm"
_FRONTEND_CMD = [_NPM, "run", "dev"]


def _ensure_frontend_deps():
    """重启后 node_modules 可能缺失，启动前自动安装。"""
    node_modules = os.path.join(_FRONTEND_DIR, "node_modules")
    if os.path.isdir(node_modules):
        return
    if not _NPM or not shutil.which(_NPM):
        print("[!] 未找到 npm，无法自动安装前端依赖，前端可能无法启动。")
        return
    print("[INFO] frontend/node_modules 缺失，自动执行 npm install...")
    subprocess.run([_NPM, "install", "--no-audit", "--no-fund"], cwd=_FRONTEND_DIR, check=False)
    print("[OK] 前端依赖安装完成。")


def _wait_for_port(host: str, port: int, timeout: float = 30.0):
    """简单探测端口是否已监听，用于给出更友好的启动提示。

    Vite 默认绑定到 ``localhost``，在某些系统上 ``127.0.0.1`` 可能解析不一致，
    所以探测失败时会再尝试 ``localhost``。
    """
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        for h in (host, "localhost"):
            try:
                with socket.create_connection((h, port), timeout=1):
                    return True
            except OSError:
                pass
        time.sleep(0.5)
    return False


def main():
    print("=" * 60)
    print("  EDM-Takens Web MVP 启动器")
    print("=" * 60)

    # 重启后 node_modules 可能缺失，提前检查安装
    _ensure_frontend_deps()

    # P1 fix: 先启动后端并等待就绪，再启动前端。
    # 后端启动时会运行 sync_check 等导入逻辑，耗时较长；
    # 若前端先就绪，浏览器会立即请求 /api/* 导致 ECONNREFUSED。
    backend = subprocess.Popen(
        _BACKEND_CMD,
        cwd=_PROJECT_ROOT,
        stdout=None,
        stderr=None,
    )
    print(f"[+] 后端 PID {backend.pid}: {' '.join(_BACKEND_CMD)}")
    print("[*] 等待后端就绪 (sync_check + 导入可能需要数秒)...")

    ready_be = _wait_for_port("127.0.0.1", 8000, timeout=60.0)
    if not ready_be:
        print("[!] 后端未能在预期时间内就绪，请检查端口 8000 是否被占用。")
        if backend.poll() is None:
            backend.terminate()
        return
    if backend.poll() is not None:
        print("[!] 后端进程已意外退出。")
        return
    print("[OK] 后端已就绪: http://localhost:8000")

    frontend = subprocess.Popen(
        _FRONTEND_CMD,
        cwd=os.path.join(_PROJECT_ROOT, "frontend"),
        stdout=None,
        stderr=None,
    )
    print(f"[+] 前端 PID {frontend.pid}: {' '.join(_FRONTEND_CMD)}")
    print("[*] 等待前端就绪...")

    ready_fe = _wait_for_port("127.0.0.1", 5173, timeout=30.0)
    if ready_fe:
        print("[OK] 前端已就绪: http://localhost:5173")
    else:
        print("[!] 前端未能在预期时间内就绪（若 5173 被占，Vite 会自动换端口）。")

    print("\n[*] 按 Ctrl+C 停止所有服务\n")

    try:
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[*] 收到中断信号，正在停止...")
    finally:
        for p, name in [(backend, "后端"), (frontend, "前端")]:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
                print(f"[-] {name} 已停止")


if __name__ == "__main__":
    main()
