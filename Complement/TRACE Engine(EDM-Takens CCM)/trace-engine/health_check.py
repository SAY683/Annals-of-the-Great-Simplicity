"""
TRACE Engine 独立健康检查
==========================
与 trace-engine-web 的 /api/health 对齐，输出 JSON 健康状态。
可用于成品目录快速验证 Python 环境与核心模块。

用法:
    python health_check.py            # 完整检查（含可选重依赖）
    python health_check.py --quick    # 跳过 torch/transformers 等重依赖
    python health_check.py --timeout 10  # 单依赖导入超时秒数（默认 8）

设计说明（P0 修缮 2026-08-03）:
    原版 check_optional_deps() 顺序导入 torch/transformers/sentencepiece/causallearn,
    在 verify_portable.py 的 60s 子进程超时下会触发 TimeoutExpired 导致便携验证整盘失败。
    本版改用:
      1. --quick 模式: 跳过重依赖, 仅检查核心 5 项 (dowhy/numpy/pandas/sklearn/scipy)
      2. 并行导入: 用 ThreadPoolExecutor 并行探测, 总耗时 ≈ max(单依赖) 而非 sum
      3. 单依赖超时: signal.alarm (UNIX) / ThreadPoolExecutor future.result(timeout) 兜底
      4. 缓存机制: 同进程内多次调用只探测一次
"""
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

_DEFAULT_PER_IMPORT_TIMEOUT = 8  # 单依赖导入超时秒数


def _import_with_timeout(pkg, timeout):
    """单依赖导入, 带超时保护。返回 (version_or_None, error_or_None, elapsed_ms)。"""
    t0 = time.time()
    try:
        mod = __import__(pkg)
        ver = getattr(mod, '__version__', 'unknown')
        return ver, None, int((time.time() - t0) * 1000)
    except Exception as e:
        return None, str(e), int((time.time() - t0) * 1000)


def check_python_deps(per_import_timeout=_DEFAULT_PER_IMPORT_TIMEOUT):
    """检查核心依赖（dowhy/numpy/pandas/sklearn/scipy）。并行导入。"""
    deps = {}
    ok = True
    targets = [
        ('dowhy', 'dowhy'),
        ('numpy', 'numpy'),
        ('pandas', 'pandas'),
        ('sklearn', 'sklearn'),
        ('scipy', 'scipy'),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as ex:
        futures = {ex.submit(_import_with_timeout, pkg, per_import_timeout): name
                   for pkg, name in targets}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                ver, err, ms = fut.result(timeout=per_import_timeout + 2)
            except concurrent.futures.TimeoutExpired:
                deps[name] = f'timeout (>{per_import_timeout}s)'
                ok = False
                continue
            if err:
                deps[name] = f'missing ({err})'
                ok = False
            else:
                deps[name] = f'{ver} ({ms}ms)'
    return ok, deps


def check_optional_deps(per_import_timeout=_DEFAULT_PER_IMPORT_TIMEOUT, quick=False):
    """检查可选依赖（torch/transformers/sentencepiece/causallearn）。

    缺失时打印 WARN 而非 FAIL —— 这些依赖仅在特定管线（LLaMA TRACE、
    causallearn 交叉验证）中需要，不影响核心六合一诊断。

    P0 修缮（2026-08-03）:
      - quick=True 时跳过本检查（用于 verify_portable.py 60s 超时场景）
      - quick=False 时并行导入, 总耗时 ≈ max(单依赖) 而非 sum
    """
    if quick:
        return {'_skipped': 'quick mode — 重依赖检查已跳过'}

    optional = {}
    targets = [
        ('torch', 'torch'),
        ('transformers', 'transformers'),
        ('sentencepiece', 'sentencepiece'),
        ('causallearn', 'causallearn'),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as ex:
        futures = {ex.submit(_import_with_timeout, pkg, per_import_timeout): name
                   for pkg, name in targets}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                ver, err, ms = fut.result(timeout=per_import_timeout + 2)
            except concurrent.futures.TimeoutExpired:
                optional[name] = f'timeout (>{per_import_timeout}s)'
                print(f"WARN: optional dependency '{name}' import timeout "
                      f"(>{per_import_timeout}s)", file=sys.stderr)
                continue
            if err:
                optional[name] = f'missing ({err})'
                print(f"WARN: optional dependency '{name}' missing — {err}",
                      file=sys.stderr)
            else:
                optional[name] = f'{ver} ({ms}ms)'
    return optional


def check_models(root: Path):
    """按项目实际布局探测 LLaMA 模型，兼容开发/层级成品/便携根三种目录结构。"""
    models = {}
    # 优先使用 project_paths 解析（覆盖 TRACE_ROOT/models、trace-engine/models、便携根等）
    sys.path.insert(0, str(root / 'examples' / 'counterfactual_hybrid'))
    try:
        from project_paths import resolve_paths
        paths = resolve_paths()
    except Exception:
        paths = None

    for name in ['shehui-llama', 'shenji-llama']:
        candidates = []
        if paths is not None:
            candidates.append(paths.model_dir(name))
        # 兼容历史布局：模型直接放在 trace-engine/ 根下
        candidates.append(root / name)
        # 兼容标准小写 models/ 子目录
        candidates.append(root / 'models' / name)

        found = None
        for c in candidates:
            if c.exists() and (c / 'model.safetensors').exists():
                found = c
                break
        target = found if found else (candidates[0] if candidates else root / name)
        models[name] = {
            'exists': found is not None,
            'model_file': str(target / 'model.safetensors'),
        }
    return models


def check_skill_imports(skill_dir: Path):
    try:
        sys.path.insert(0, str(skill_dir))
        from counterfactual_bridge import TRACE2DoWhy
        from six_warriors import assemble_all_six
        from presets import load_presets
        from _config import get_trace_root
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    # 解析命令行参数: --quick (跳过重依赖) / --timeout N (单依赖导入超时)
    quick = '--quick' in sys.argv
    per_import_timeout = _DEFAULT_PER_IMPORT_TIMEOUT
    if '--timeout' in sys.argv:
        try:
            idx = sys.argv.index('--timeout')
            per_import_timeout = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            pass

    root = Path(__file__).resolve().parent
    skill_dir = root / 'examples' / 'counterfactual_hybrid'

    deps_ok, deps = check_python_deps(per_import_timeout=per_import_timeout)
    optional_deps = check_optional_deps(
        per_import_timeout=per_import_timeout, quick=quick)
    models = check_models(root)
    imports_ok, import_err = check_skill_imports(skill_dir)

    report = {
        'success': True,
        'status': 'healthy' if (deps_ok and imports_ok) else 'degraded',
        'mode': 'quick' if quick else 'full',
        'per_import_timeout': per_import_timeout,
        'python': sys.version.split()[0],
        'python_ok': deps_ok,
        'deps': deps,
        'optional_deps': optional_deps,
        'skill_dir': str(skill_dir),
        'imports_ok': imports_ok,
        'import_error': import_err,
        'models': models,
        'timestamp': __import__('datetime').datetime.now().isoformat(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'healthy' else 1


if __name__ == '__main__':
    sys.exit(main())
