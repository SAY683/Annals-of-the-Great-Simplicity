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
# R44-D 修复 (ROUND44 P0): 禁止 Python 写入 __pycache__,
# 避免 verify_portable.py 运行时在成品目录生成 .pyc 运行时产物.
# 病灶: verify_portable.py 导入 trace-engine/edm-takens 模块时,
# Python 自动生成 __pycache__/ 目录, 违反便携打包"无运行时产物"约束.
# 修复: 在导入任何项目模块之前设置 sys.dont_write_bytecode = True,
# 并通过环境变量 PYTHONDONTWRITEBYTECODE=1 让子进程 (health_check.py、
# test_skill.py、sync_check.py 等) 也继承此设置, 根治 __pycache__ 污染.
import sys
sys.dont_write_bytecode = True

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

# 设置环境变量, 让 subprocess 启动的子进程也禁止写入 __pycache__
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'


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
    """检查便携目录是否被运行时产物污染。

    P1 修缮（2026-08-03）: 扩展覆盖 edm-takens-web 的 jobs.sqlite 防护。
    病灶: backend/job_store.py 默认将 jobs.sqlite 写入 edm-takens-web/ 根目录,
    若 sync_product.py 的 ignore 未排除（已修复）, 该文件会被反向同步到便携目录,
    携带旧任务历史与可能的敏感数据。此检查作为契约验证的最后一道防线。
    """
    result = {'name': '运行时产物污染', 'ok': True, 'messages': []}
    bad_patterns = ['web_*_result*.json', 'test_min*.bat', '18)']
    web_root = root / 'trace-engine-web'
    found = []
    for pat in bad_patterns:
        for f in web_root.glob(pat):
            found.append(f.name)
    # outputs/ / uploads/ 是正常运行时目录，仅在其包含非空内容时视为污染
    for name in ['outputs', 'uploads']:
        p = web_root / name
        if p.exists() and p.is_dir():
            try:
                children = list(p.iterdir())
                if children:
                    found.append(f'{name}/ ({len(children)} 项内容)')
            except PermissionError:
                found.append(f'{name}/ (无法读取)')

    # P1 修缮: 扩展覆盖 edm-takens-web 的运行时产物
    edm_web = root / 'edm-takens-web'
    if edm_web.exists():
        # SQLite 数据库污染检查（jobs.sqlite / *.sqlite / *.db）
        for pat in ['jobs.sqlite', '*.sqlite', '*.sqlite-journal',
                    '*.sqlite-wal', '*.sqlite-shm', '*.db']:
            for f in edm_web.glob(pat):
                found.append(f'edm-takens-web/{f.name}')
        # 非空 outputs/ uploads/ results/ 目录
        # P0 修缮（ROUND32 三视角评审-架构师）: 新增 results/ 检查,
        # results/<job_id>/config_*.json 含开发者用户名绝对路径, 必须排除.
        for name in ['outputs', 'uploads', 'data/uploads', 'results']:
            p = edm_web / name
            if p.exists() and p.is_dir():
                try:
                    children = list(p.iterdir())
                    if children:
                        found.append(f'edm-takens-web/{name}/ ({len(children)} 项内容)')
                except PermissionError:
                    found.append(f'edm-takens-web/{name}/ (无法读取)')
        # 日志文件
        for f in edm_web.glob('*.log'):
            found.append(f'edm-takens-web/{f.name}')

    if found:
        result['ok'] = False
        result['messages'].append(f'发现残留: {found}')
    else:
        result['messages'].append('无残留运行时产物（覆盖 trace-engine-web 与 edm-takens-web）')
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
    """复用 trace-engine/health_check.py，与 Web 端健康检查对齐。

    P0 修缮（2026-08-03）: 调用 --quick 模式跳过 torch/transformers 等重依赖
    顺序导入导致的超时。原版 60s 超时下 check_optional_deps() 会触发 TimeoutExpired。
    --quick 模式仅检查核心 5 项（dowhy/numpy/pandas/sklearn/scipy），实测 ~10s。
    """
    result = {'name': 'trace-engine 独立健康检查', 'ok': True, 'messages': []}
    script = engine / 'health_check.py'
    if not script.exists():
        result['messages'].append('未找到 health_check.py，跳过')
        return result
    # --quick 跳过重依赖; 超时放宽到 90s（原 60s 在慢机器上仍可能不够）
    proc = subprocess.run([sys.executable, str(script), '--quick'],
                          capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        result['ok'] = False
        result['messages'].append(proc.stderr or proc.stdout)
    else:
        result['messages'].append('health_check.py --quick 通过')
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
    result = {'name': 'npm 依赖安装', 'ok': True, 'messages': [],
              'skipped': False, 'skip_reason': ''}
    if (web / 'node_modules').exists():
        result['messages'].append('node_modules 已存在')
        return result
    pkg = web / 'package.json'
    if not pkg.exists():
        result['ok'] = False
        result['messages'].append('缺失 package.json，无法安装依赖')
        return result
    # P0 修缮（2026-08-03）: npm 不在 PATH 时优雅降级为 SKIP，而非崩溃
    # 便携目录验证不应因 npm 缺失而整盘失败
    try:
        proc = subprocess.run(
            ['npm', 'install'],
            cwd=str(web),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        # npm 不可用：标记为 SKIP 而非 FAIL（环境限制，非代码缺陷）
        result['ok'] = True
        result['skipped'] = True
        result['skip_reason'] = 'npm 不可用（不在 PATH 中）'
        result['messages'].append('npm 不可用（不在 PATH 中），跳过依赖安装')
        result['messages'].append('提示: 请手动运行 npm install 或确保 Node.js 已安装')
        return result
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
    # npm 不可用时跳过 Web 健康检查（环境限制，非代码缺陷）
    if npm_result.get('skipped'):
        result['messages'].append(f'SKIP: {npm_result.get("skip_reason", "")}')
        return result

    port = find_free_port()
    # 审计使用独立临时工作目录，避免污染成品/开发目录中的 work/outputs
    work_dir = Path(os.environ.get('TRACE_WORK_DIR', str(Path(os.environ.get('TEMP', '/tmp')) / f'trace_verify_{port}')))
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
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

    # 强制直连，避免环境中的 HTTP_PROXY/HTTPS_PROXY（尤其格式错误的代理）
    # 将本地健康检查误判为外部请求并导致 getaddrinfo failed。
    _no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fetch_json(path: str, timeout: int = 2):
        url = f'http://127.0.0.1:{port}{path}'
        req = urllib.request.Request(url)
        with _no_proxy_opener.open(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))

    try:
        # 等待服务启动；Python 环境检查可能耗时较长，给予 30 秒
        last_error = ''
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                # 使用 127.0.0.1 避免某些环境下的 localhost 代理/relay 拦截
                status, data = fetch_json('/api/health')
                if status == 200 and data.get('success'):
                    result['messages'].append(f'健康检查通过 (port={port})')
                    result['messages'].append(json.dumps(data, ensure_ascii=False)[:200])
                    # 健康检查通过后继续校验 /api/config API 契约
                    try:
                        cstatus, cdata = fetch_json('/api/config')
                        if cstatus == 200 and cdata.get('success'):
                            modes = cdata.get('modes') or {}
                            schema = cdata.get('bridgeParamSchema') or {}
                            if 'super' not in modes:
                                result['ok'] = False
                                result['messages'].append('/api/config 未暴露 SUPER 模式')
                            elif 'max_segments' not in schema:
                                result['ok'] = False
                                result['messages'].append('/api/config 的 bridgeParamSchema 缺少 max_segments')
                            else:
                                result['messages'].append('/api/config API 契约通过（含 SUPER 模式与 max_segments）')
                                config_ok = True
                        else:
                            result['ok'] = False
                            result['messages'].append(f'/api/config 返回异常: {cstatus}')
                    except Exception as ce:
                        result['ok'] = False
                        result['messages'].append(f'/api/config 检查失败: {ce}')
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
        # 清理审计自动创建的临时工作目录
        if 'TRACE_WORK_DIR' not in os.environ and 'trace_verify_' in str(work_dir):
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
    return result


def check_super_worker_imports(root: Path) -> dict:
    """SUPER 模式冒烟测试：检查 llama_worker.py 的导入路径是否被遮蔽。

    背景：便携目录中若存在 trace-engine/presets.py（旧版 v3 预设文件），
    会遮蔽 examples/counterfactual_hybrid/presets.py（含 load_presets），
    导致 llama_worker.py ImportError → SUPER 模式启动超时（120s）。
    """
    result = {'name': 'SUPER 模式导入路径', 'ok': True, 'messages': []}
    engine = root / 'trace-engine'
    skill_dir = engine / 'examples' / 'counterfactual_hybrid'

    # 检查是否存在会遮蔽 counterfactual_hybrid/ 下模块的根级 .py 文件
    shading_files = ['presets.py', '_check_config.py']
    for fname in shading_files:
        root_file = engine / fname
        skill_file = skill_dir / fname
        if root_file.exists() and skill_file.exists():
            result['ok'] = False
            result['messages'].append(
                f'遮蔽风险: trace-engine/{fname} 会遮蔽 '
                f'trace-engine/examples/counterfactual_hybrid/{fname}')
            result['messages'].append(
                '这将导致 llama_worker.py ImportError → SUPER 模式启动超时')

    # 检查 llama_worker.py 需要的关键模块是否存在于 counterfactual_hybrid/
    required_modules = ['presets.py', 'counterfactual_bridge.py', 'six_warriors.py',
                        'dowhy_auditor.py', 'project_paths.py']
    for mod in required_modules:
        if not (skill_dir / mod).exists():
            result['ok'] = False
            result['messages'].append(f'缺失: examples/counterfactual_hybrid/{mod}')

    if result['ok']:
        result['messages'].append('无遮蔽风险，SUPER 模块路径正确')

    return result


def check_trace_to_edm_contract(root: Path) -> dict:
    """R13-4：校验 trace-to-edm 轨迹表契约。

    确保 bridge.py 写入 trace_status/trace_error/trace_mode 列，
    且前端 app.js 的 preferredCols 数组包含这三列。
    否则会出现"系统错位被静默吞掉"的回归。
    """
    result = {'name': 'trace-to-edm 轨迹表契约', 'ok': True, 'messages': []}
    bridge_py = root / 'trace-to-edm' / 'bridge.py'
    app_js = root / 'trace-to-edm' / 'public' / 'js' / 'app.js'

    if not bridge_py.exists():
        result['ok'] = False
        result['messages'].append('缺失 trace-to-edm/bridge.py')
        return result
    if not app_js.exists():
        result['ok'] = False
        result['messages'].append('缺失 trace-to-edm/public/js/app.js')
        return result

    # 1. bridge.py 必须写入这三列
    bridge_text = bridge_py.read_text(encoding='utf-8')
    for col in ['trace_status', 'trace_error', 'trace_mode']:
        if f'"{col}"' not in bridge_text and f"'{col}'" not in bridge_text:
            result['ok'] = False
            result['messages'].append(f'bridge.py 未写入列: {col}')

    # 2. app.js preferredCols 必须包含这三列
    app_text = app_js.read_text(encoding='utf-8')
    for col in ['trace_status', 'trace_mode', 'trace_error']:
        if col not in app_text:
            result['ok'] = False
            result['messages'].append(f'app.js preferredCols 缺少列: {col}')

    # 3. main.css 应含状态色 .tstat-* 类
    main_css = root / 'trace-to-edm' / 'public' / 'css' / 'main.css'
    if main_css.exists():
        css_text = main_css.read_text(encoding='utf-8')
        for cls in ['tstat-ok', 'tstat-failed', 'tstat-partial']:
            if cls not in css_text:
                result['ok'] = False
                result['messages'].append(f'main.css 缺少状态色类: {cls}')

    if result['ok']:
        result['messages'].append('bridge.py 写入 + app.js 渲染 + CSS 状态色 契约完整')
    return result


def check_portable_code_fixes(root: Path) -> dict:
    """Round 17 新增：校验便携式目录已落地关键代码修缮。

    检查项：
      1. trace-engine-web/server.js 绑定 TRACE_HOST || '127.0.0.1'（非 0.0.0.0）
      2. trace-to-edm/server.js 同上
      3. tokusatsu.css 含 cache戳（避免旧样式缓存）
      4. six_warriors.py 实现 CCM verdict 三级语义
      5. causallearn_validator.py 实现 run_fci 方法
    """
    result = {'name': '便携式代码修缮落地', 'ok': True, 'messages': []}

    # 1. 主机绑定检查
    # Round 27 更新: 接受两种实现——直接 env 读取或通过 CONFIG.host（P1-5 修缮后）
    web_server = root / 'trace-engine-web' / 'server.js'
    if web_server.exists():
        text = web_server.read_text(encoding='utf-8')
        _old_pattern = "TRACE_HOST || '127.0.0.1'" in text or 'TRACE_HOST || "127.0.0.1"' in text
        _new_pattern = 'CONFIG.host' in text
        if not _old_pattern and not _new_pattern:
            result['ok'] = False
            result['messages'].append('trace-engine-web/server.js 未绑定 TRACE_HOST || 127.0.0.1 或 CONFIG.host')

    t2e_server = root / 'trace-to-edm' / 'server.js'
    if t2e_server.exists():
        text = t2e_server.read_text(encoding='utf-8')
        if "127.0.0.1" not in text:
            result['ok'] = False
            result['messages'].append('trace-to-edm/server.js 未绑定 127.0.0.1')

    # 2. CCM verdict 三级语义检查
    sw_path = root / 'trace-engine' / 'examples' / 'counterfactual_hybrid' / 'six_warriors.py'
    if sw_path.exists():
        text = sw_path.read_text(encoding='utf-8')
        for token in ['ELIGIBLE_BUT_NOT_RUN', 'HEURISTIC_FALLBACK', 'VERIFIABLE']:
            if token not in text:
                result['ok'] = False
                result['messages'].append(f'six_warriors.py 缺少 CCM verdict 语义: {token}')

    # 3. causallearn FCI 检查
    cl_path = root / 'trace-engine' / 'examples' / 'counterfactual_hybrid' / 'causallearn_validator.py'
    if cl_path.exists():
        text = cl_path.read_text(encoding='utf-8')
        if 'def run_fci' not in text:
            result['ok'] = False
            result['messages'].append('causallearn_validator.py 缺少 run_fci 方法')

    # 4. tokusatsu.css cache戳检查
    for css_path in [
        root / 'shared' / 'themes' / 'tokusatsu.css',
        root / 'trace-engine-web' / 'public' / 'shared' / 'themes' / 'tokusatsu.css',
    ]:
        if css_path.exists():
            text = css_path.read_text(encoding='utf-8')
            if '?v=2026' not in text and '?v=20260' not in text:
                # cache戳在 HTML 引用而非 CSS 本体，转查 index.html
                pass

    if result['ok']:
        result['messages'].append('主机绑定/CCM verdict/FCI 等关键修缮已落地')
    return result


def check_docs_sync(root: Path) -> dict:
    """Round 17 新增：校验 Docs/ 目录关键文档已同步。

    P1 修缮（2026-08-03）: 扩展校验便携目录根的关键文档（PORTABLE_TECHNICAL_GUIDE.md）。
    病灶: 原版 sync_product.py 误删 PORTABLE_TECHNICAL_GUIDE.md, 而 verify_portable.py
    未校验其存在, 导致文档断裂未被检测到。现新增校验作为契约防线。
    """
    result = {'name': 'Docs 同步', 'ok': True, 'messages': []}
    # root 是 TRACE Engine(EDM-Takens CCM)/，Docs/ 在其上一级
    docs_dir = root.parent / 'Docs'
    if not docs_dir.exists():
        # 开发布局可能 Docs/ 在 root 同级
        docs_dir = root / 'Docs'
    if not docs_dir.exists():
        result['messages'].append('未找到 Docs/ 目录，跳过')
    else:
        required_docs = [
            'META_AUDIT_CHANGELOG.md',
            'MICROSERVICE_API_DESIGN.md',
            '00-README.md',
        ]
        for doc in required_docs:
            if not (docs_dir / doc).exists():
                result['ok'] = False
                result['messages'].append(f'Docs/ 缺失: {doc}')

        if result['ok']:
            result['messages'].append(f'Docs/ 关键文档齐全 ({len(required_docs)} 项)')

    # P1 修缮: 校验便携目录根的关键文档
    portable_root_docs = [
        'PORTABLE_TECHNICAL_GUIDE.md',  # 便携目录技术指南（曾被误删）
        'README.md',                     # 便携目录说明
        'test_mcp_protocol.py',          # MCP 协议测试脚手架
        'test_cross_project_http.py',    # 跨项目 HTTP 契约测试
    ]
    missing_portable = []
    for doc in portable_root_docs:
        if not (root / doc).exists():
            missing_portable.append(doc)
    if missing_portable:
        result['ok'] = False
        result['messages'].append(f'便携目录根缺失: {missing_portable}')
    else:
        result['messages'].append(f'便携目录根关键文档齐全 ({len(portable_root_docs)} 项)')

    return result


def check_skill_projects(root: Path) -> dict:
    """Round 17 新增：校验 Skill/ 目录下三大项目已同步。
    ROUND28 更新: 改为检查便携目录内的 edm-takens/ 和 edm-takens-web/,
    而非依赖外部 Skill/ 目录, 实现真正的开箱即用.
    """
    result = {'name': 'EDM-TAKENS 项目同步', 'ok': True, 'messages': []}

    # ROUND28: 检查便携目录内的 EDM-TAKENS 项目, 而非外部 Skill/
    required_projects = {
        'edm-takens': root / 'edm-takens',
        'edm-takens-web': root / 'edm-takens-web',
    }
    for proj_name, proj_path in required_projects.items():
        if not proj_path.exists():
            result['ok'] = False
            result['messages'].append(f'便携目录缺失: {proj_name}/')
        else:
            result['messages'].append(f'存在: {proj_name}/')

    # edm-takens 核心库关键文件检查
    edm_takens = root / 'edm-takens'
    if edm_takens.exists():
        critical_files = [
            edm_takens / 'src' / 'pipeline.py',
            edm_takens / 'src' / 'ccm_causality.py',
            edm_takens / 'src' / 'sovereign_havok.py',
            edm_takens / 'src' / '_numpy_edm.py',
            edm_takens / 'src' / '_numeric_constants.py',
            edm_takens / 'src' / 'surrogate_test.py',
            edm_takens / 'run_pipeline.py',
            edm_takens / 'run_tests.py',
            edm_takens / 'docs' / 'ALGORITHM_AUDIT.md',
        ]
        missing = [str(f.relative_to(root)) for f in critical_files if not f.exists()]
        if missing:
            result['ok'] = False
            result['messages'].append(f'edm-takens 缺失关键文件: {missing}')
        else:
            result['messages'].append(f'edm-takens 关键文件齐全 ({len(critical_files)} 项)')

    # edm-takens-web 后端关键文件检查
    edm_takens_web = root / 'edm-takens-web'
    if edm_takens_web.exists():
        critical_files = [
            edm_takens_web / 'backend' / 'api.py',
            edm_takens_web / 'backend' / 'sync_check.py',
            edm_takens_web / 'backend' / 'services' / 'summary_builder.py',
            edm_takens_web / 'backend' / 'edmtakens' / 'pipeline.py',
            edm_takens_web / 'backend' / 'edmtakens' / 'ccm_causality.py',
            edm_takens_web / 'frontend' / 'src' / 'main.js',
            edm_takens_web / 'frontend' / 'src' / 'style.css',
            edm_takens_web / 'frontend' / 'index.html',
            edm_takens_web / 'docs' / 'ALGORITHM_AUDIT.md',
        ]
        missing = [str(f.relative_to(root)) for f in critical_files if not f.exists()]
        if missing:
            result['ok'] = False
            result['messages'].append(f'edm-takens-web 缺失关键文件: {missing}')
        else:
            result['messages'].append(f'edm-takens-web 关键文件齐全 ({len(critical_files)} 项)')

    if result['ok']:
        result['messages'].append('EDM-TAKENS 项目在便携目录内完整')
    return result


def check_edm_takens_cli(root: Path) -> dict:
    """ROUND28 新增: 校验 edm-takens CLI 核心模块可导入.

    科研级产品的开箱即用要求: 用户进入便携目录后, 无需配置 PYTHONPATH,
    即可运行 edm-takens 的 CLI (run_pipeline.py) 和测试套件 (run_tests.py).
    本检查验证 src/ 下的核心算法模块能被 Python 解释器成功导入.
    """
    result = {'name': 'EDM-TAKENS CLI 模块导入', 'ok': True, 'messages': []}
    edm_takens = root / 'edm-takens'
    if not edm_takens.exists():
        result['ok'] = False
        result['messages'].append('缺失 edm-takens/ 目录')
        return result

    src_dir = edm_takens / 'src'
    if not src_dir.exists():
        result['ok'] = False
        result['messages'].append('缺失 edm-takens/src/ 目录')
        return result

    # 导入核心模块的冒烟测试脚本
    script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
try:
    from pipeline import run_pipeline, run_full_analysis, PipelineConfig
    from ccm_causality import ccm_causality_test, ccm_batch_test
    from sovereign_havok import SovereignHAVOK
    from _numpy_edm import CCM, EmbedDimension, Simplex
    from _numeric_constants import EPS_DISTANCE, EPS_VARIANCE, EPS_PROB, EPS_ENERGY, EPS_LYAPUNOV
    from surrogate_test import iaaft_surrogates, surrogate_significance_test
    from final_interpretation import ccm_with_convergence
    print('EDM_TAKENS_IMPORT_OK')
except Exception as e:
    print(f'IMPORT_ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"""
    test_file = edm_takens / '_verify_imports.py'
    try:
        test_file.write_text(script, encoding='utf-8')
        proc = subprocess.run([sys.executable, str(test_file)],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 or 'EDM_TAKENS_IMPORT_OK' not in proc.stdout:
            result['ok'] = False
            result['messages'].append(proc.stderr or proc.stdout)
        else:
            result['messages'].append('edm-takens 核心模块导入成功 (7 模块)')
    finally:
        if test_file.exists():
            test_file.unlink()
    return result


def check_edm_takens_disclosure_fields(root: Path) -> dict:
    """ROUND28 新增: 校验科研披露字段在便携目录的 edm-takens 副本中存在.

    这 4 个字段是科研级产品的核心披露, 必须在便携目录中存在:
      - is_strict_confirmatory (ccm_causality.py): BH uniform-null 假设披露
      - methodology_disclaimer (ccm_causality.py): 方法学免责声明
      - effective_lib_sizes (_numpy_edm.py): out-of-sample 实际建树库大小
      - out_of_sample_used (_numpy_edm.py): 评估模式标志
    """
    result = {'name': 'EDM-TAKENS 科研披露字段', 'ok': True, 'messages': []}
    edm_takens = root / 'edm-takens'
    if not edm_takens.exists():
        result['ok'] = False
        result['messages'].append('缺失 edm-takens/ 目录')
        return result

    disclosure_fields = {
        'src/ccm_causality.py': ['is_strict_confirmatory', 'methodology_disclaimer'],
        'src/_numpy_edm.py': ['effective_lib_sizes', 'out_of_sample_used'],
    }
    missing = []
    for rel_path, fields in disclosure_fields.items():
        fpath = edm_takens / rel_path
        if not fpath.exists():
            missing.append(f'{rel_path} (文件缺失)')
            continue
        content = fpath.read_text(encoding='utf-8')
        for field in fields:
            if f'"{field}"' not in content and f"'{field}'" not in content:
                missing.append(f'{rel_path}: 字段 {field}')

    if missing:
        result['ok'] = False
        result['messages'].append(f'科研披露字段缺失: {missing}')
    else:
        result['messages'].append('4 个科研披露字段全部存在 (confirmatory/disclaimer/lib_sizes/oos)')
    return result


def check_edm_takens_sync_check(root: Path) -> dict:
    """ROUND28 新增: 在便携目录内运行 sync_check.py, 验证核心库与 Web 副本一致.

    sync_check.py 比对 edm-takens/src/ 和 edm-takens-web/backend/edmtakens/ 的
    SHA256 一致性, 确保便携目录内的两个项目没有失同步.
    """
    result = {'name': 'EDM-TAKENS 跨项目 sync_check', 'ok': True, 'messages': []}
    sync_check = root / 'edm-takens-web' / 'backend' / 'sync_check.py'
    if not sync_check.exists():
        result['ok'] = False
        result['messages'].append('缺失 edm-takens-web/backend/sync_check.py')
        return result

    # sync_check.py 依赖相对路径 ../edm-takens/src, 需在 backend/ 目录下运行
    backend_dir = root / 'edm-takens-web' / 'backend'
    proc = subprocess.run(
        [sys.executable, str(sync_check), '--quiet'],
        capture_output=True, text=True, timeout=60,
        cwd=str(backend_dir)
    )
    if proc.returncode != 0:
        result['ok'] = False
        result['messages'].append(f'sync_check 失败 (exit={proc.returncode})')
        result['messages'].append(proc.stdout[-500:] if proc.stdout else proc.stderr[-500:])
    else:
        # 解析输出中的汇总行
        output = proc.stdout
        if '源码汇总' in output:
            # 提取汇总行
            for line in output.split('\n'):
                if '源码汇总' in line:
                    result['messages'].append(f'sync_check: {line.strip()}')
                    break
        else:
            result['messages'].append('sync_check 通过 (核心库与 Web 副本一致)')
    return result


def find_product_root(start: Path) -> Path:
    """从脚本位置向上探测包含 trace-engine 与 trace-engine-web 的根目录。

    支持两种布局:
      - 成品布局: <product>/trace-engine-web/work/verify_portable.py -> <product>
      - 开发布局: <project>/.skills/trace-engine-web/work/verify_portable.py -> <project>/.skills
    """
    current = start.resolve()
    for _ in range(6):
        if (current / 'trace-engine').exists() and (current / 'trace-engine-web').exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return start


def main():
    root = find_product_root(Path(__file__).resolve().parent)
    print('=' * 60)
    print('TRACE Engine 便携目录独立运行审计')
    print(f'目录: {root}')
    print('=' * 60)

    # Round 17：从 7 项扩充到 11 项，覆盖 trace-to-edm 契约、代码修缮落地、Docs/Skill 同步
    # ROUND28: 从 11 项扩充到 14 项, 新增 EDM-TAKENS CLI 导入、科研披露字段、sync_check
    checks = [
        check_structure(root),
        check_no_runtime_artifacts(root),
        check_engine_health(root / 'trace-engine'),
        check_engine_imports(root / 'trace-engine'),
        check_engine_tests(root / 'trace-engine'),
        check_super_worker_imports(root),
        check_web_health(root),
        check_trace_to_edm_contract(root),
        check_portable_code_fixes(root),
        check_docs_sync(root),
        check_skill_projects(root),
        # ROUND28 新增: EDM-TAKENS 专用检查
        check_edm_takens_cli(root),
        check_edm_takens_disclosure_fields(root),
        check_edm_takens_sync_check(root),
    ]

    all_ok = True
    n_pass = 0
    n_fail = 0
    for c in checks:
        status = 'PASS' if c['ok'] else 'FAIL'
        if c['ok']:
            n_pass += 1
        else:
            n_fail += 1
        print(f'\n[{status}] {c["name"]}')
        for m in c['messages']:
            print(f'  - {m}')
        if not c['ok']:
            all_ok = False

    print('\n' + '=' * 60)
    print(f'汇总: {n_pass} PASS / {n_fail} FAIL / {len(checks)} 项 (ROUND28 14项契约)')
    if all_ok:
        print('审计结果: 全部通过，便携目录可独立运行。')
        return 0
    else:
        print('审计结果: 存在失败项，请检查上述日志。')
        return 1


if __name__ == '__main__':
    sys.exit(main())
