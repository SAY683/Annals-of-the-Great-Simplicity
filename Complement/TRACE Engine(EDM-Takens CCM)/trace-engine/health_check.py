"""
TRACE Engine 独立健康检查
==========================
与 trace-engine-web 的 /api/health 对齐，输出 JSON 健康状态。
可用于成品目录快速验证 Python 环境与核心模块。

用法:
    python health_check.py
"""
import json
import os
import sys
from pathlib import Path


def check_python_deps():
    deps = {}
    ok = True
    for pkg, name in [
        ('dowhy', 'dowhy'),
        ('numpy', 'numpy'),
        ('pandas', 'pandas'),
        ('sklearn', 'sklearn'),
        ('scipy', 'scipy'),
    ]:
        try:
            mod = __import__(pkg)
            deps[name] = getattr(mod, '__version__', 'unknown')
        except Exception as e:
            deps[name] = f'missing ({e})'
            ok = False
    return ok, deps


def check_models(root: Path):
    models = {}
    for name in ['Shehui-LLaMA', 'Shenji-LLaMA']:
        model_dir = root / name
        models[name] = {
            'exists': model_dir.exists(),
            'model_file': str(model_dir / 'model.safetensors'),
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
    root = Path(__file__).resolve().parent
    skill_dir = root / 'examples' / 'counterfactual_hybrid'

    deps_ok, deps = check_python_deps()
    models = check_models(root)
    imports_ok, import_err = check_skill_imports(skill_dir)

    report = {
        'success': True,
        'status': 'healthy' if (deps_ok and imports_ok) else 'degraded',
        'python': sys.version.split()[0],
        'python_ok': deps_ok,
        'deps': deps,
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
