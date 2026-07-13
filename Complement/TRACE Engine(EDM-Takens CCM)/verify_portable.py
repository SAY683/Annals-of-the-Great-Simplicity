"""
TRACE Engine 便携目录独立运行审计脚本
======================================
验证成品/便携目录中的 trace-engine 与 trace-engine-web 能否独立运行。

用法:
    python verify_portable.py

检查项:
    1. 目录结构（trace-engine/ 与 trace-engine-web/ 存在）
    2. trace-engine 核心模块可导入
    3. trace-engine 自检测试可通过
    4. trace-engine-web 服务端可启动并接受健康检查
    5. 关键文件存在且无运行时产物污染
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def find_free_port(start=3030, end=3050):
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    raise RuntimeError('未找到空闲端口')


def check_structure(root: Path) -> dict:
    result = {'name': '目录结构', 'ok': True, 'messages': []}
    required = ['trace-engine', 'trace-engine-web']
    for name in required:
        p = root / name
        if not p.exists():
            result['ok'] = False
            result['messages'].append(f'缺失: {name}/')
        else:
            result['messages'].append(f'存在: {name}/')
    return result


def check_no_runtime_artifacts(root: Path) -> dict:
    result = {'name': '运行时产物污染', 'ok': True, 'messages': []}
    bad_patterns = ['web_*_result*.json', 'test_min*.bat', '18)']
    web_root = root / 'trace-engine-web'
    found = []
    for pat in bad_patterns:
        for f in web_root.glob(pat):
            found.append(f.name)
    for name in ['outputs', 'uploads']:
        if (web_root / name).exists():
            found.append(name + '/')
    if found:
        result['ok'] = False
        result['messages'].append(f'发现残留: {found}')
    else:
        result['messages'].append('无残留运行时产物')
    return result


def check_engine_imports(engine: Path) -> dict:
    result = {'name': 'trace-engine 模块导入', 'ok': True, 'messages': []}
    bridge_dir = engine / 'examples' / 'counterfactual_hybrid'
    script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from counterfactual_bridge import TRACE2DoWhy
from six_warriors import assemble_all_six
from presets import load_presets
from _config import get_trace_root, get_trace_data_dir
print('IMPORT_OK')
"""
    test_file = bridge_dir / '_verify_imports.py'
    try:
        test_file.write_text(script, encoding='utf-8')
        proc = subprocess.run([sys.executable, str(test_file)],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 or 'IMPORT_OK' not in proc.stdout:
            result['ok'] = False
            result['messages'].append(proc.stderr or proc.stdout)
        else:
            result['messages'].append('核心模块导入成功')
    finally:
        if test_file.exists():
            test_file.unlink()
    return result


def check_engine_health(engine: Path) -> dict:
    """复用 trace-engine/health_check.py，与 Web 端健康检查对齐。"""
    result = {'name': 'trace-engine 独立健康检查', 'ok': True, 'messages': []}
    script = engine / 'health_check.py'
    if not script.exists():
        result['messages'].append('未找到 health_check.py，跳过')
        return result
    proc = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        result['ok'] = False
        result['messages'].append(proc.stderr or proc.stdout)
    else:
        result['messages'].append('health_check.py 通过')
        result['messages'].append(proc.stdout[:300])
    return result


def check_engine_tests(engine: Path) -> dict:
    result = {'name': 'trace-engine 自检测试', 'ok': True, 'messages': []}
    test_script = engine / 'tests' / 'test_skill.py'
    if not test_script.exists():
        result['ok'] = False
        result['messages'].append('缺失 tests/test_skill.py')
        return result
    proc = subprocess.run([sys.executable, str(test_script)],
                          cwd=str(engine), capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        result['ok'] = False
        result['messages'].append(proc.stderr or proc.stdout)
    else:
        result['messages'].append('test_skill.py 通过')
    return result


def install_npm_deps(web: Path) -> dict:
    result = {'name': 'npm 依赖安装', 'ok': True, 'messages': []}
    if (web / 'node_modules').exists():
        result['messages'].append('node_modules 已存在')
        return result
    pkg = web / 'package.json'
    if not pkg.exists():
        result['ok'] = False
        result['messages'].append('缺失 package.json，无法安装依赖')
        return result
    proc = subprocess.run(
        ['npm', 'install'],
        cwd=str(web),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        result['ok'] = False
        result['messages'].append('npm install 失败')
        result['messages'].append(proc.stderr or proc.stdout)
    else:
        result['messages'].append('npm install 成功')
    return result


def check_web_health(root: Path) -> dict:
    result = {'name': 'trace-engine-web 健康检查', 'ok': True, 'messages': []}
    web = root / 'trace-engine-web'
    server_js = web / 'server.js'
    if not server_js.exists():
        result['ok'] = False
        result['messages'].append('缺失 server.js')
        return result

    npm_result = install_npm_deps(web)
    result['messages'].extend(npm_result['messages'])
    if not npm_result['ok']:
        result['ok'] = False
        return result

    port = find_free_port()
    work_dir = Path(os.environ.get('TRACE_WORK_DIR', str(web / 'work')))
    work_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['PORT'] = str(port)
    env['TRACE_WORK_DIR'] = str(work_dir)
    env['TRACE_ENGINE_SKILL_DIR'] = str(root / 'trace-engine' / 'examples' / 'counterfactual_hybrid')

    proc = subprocess.Popen(
        ['node', str(server_js)],
        cwd=str(web),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # 等待服务启动；Python 环境检查可能耗时较长，给予 30 秒
        last_error = ''
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                # 使用 127.0.0.1 避免某些环境下的 localhost 代理/relay 拦截
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as resp:
                    data = resp.read().decode('utf-8')
                    if resp.status == 200:
                        result['messages'].append(f'健康检查通过 (port={port})')
                        result['messages'].append(data[:200])
                        return result
            except Exception as e:
                last_error = str(e)
                time.sleep(0.5)
        # 未通过健康检查：先标记失败，finally 中再终止进程并收集日志
        result['ok'] = False
        result['messages'].append('服务未能在 30 秒内响应健康检查')
        if last_error:
            result['messages'].append(f'最后错误: {last_error}')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        stdout, stderr = proc.stdout.read() if proc.stdout else '', proc.stderr.read() if proc.stderr else ''
        if stderr or stdout:
            result['messages'].append('服务端输出:')
            result['messages'].append(stderr or stdout)
    return result


def main():
    root = Path(__file__).resolve().parent
    print('=' * 60)
    print('TRACE Engine 便携目录独立运行审计')
    print(f'目录: {root}')
    print('=' * 60)

    checks = [
        check_structure(root),
        check_no_runtime_artifacts(root),
        check_engine_health(root / 'trace-engine'),
        check_engine_imports(root / 'trace-engine'),
        check_engine_tests(root / 'trace-engine'),
        check_web_health(root),
    ]

    all_ok = True
    for c in checks:
        status = 'PASS' if c['ok'] else 'FAIL'
        print(f'\n[{status}] {c["name"]}')
        for m in c['messages']:
            print(f'  - {m}')
        if not c['ok']:
            all_ok = False

    print('\n' + '=' * 60)
    if all_ok:
        print('审计结果: 全部通过，便携目录可独立运行。')
        return 0
    else:
        print('审计结果: 存在失败项，请检查上述日志。')
        return 1


if __name__ == '__main__':
    sys.exit(main())
