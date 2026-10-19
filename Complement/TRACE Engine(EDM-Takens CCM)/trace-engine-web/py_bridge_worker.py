#!/usr/bin/env python3
"""Persistent JSON-lines worker around py_bridge.py.

One process imports py_bridge and skill dependencies once, then handles multiple
analysis requests sequentially. The request schema is intentionally small:

  {"skill_dir": "...", "out_dir": "...", "mode": "light|deep",
   "config": {...}, "input_file": "..."}

Each response is one JSON line with ok/exit_code/stdout/stderr. The worker never
prints py_bridge's own stdout directly; it captures it for the parent to log.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import traceback
from pathlib import Path

BRIDGE = Path(__file__).with_name('py_bridge.py')


def _load_bridge():
    spec = importlib.util.spec_from_file_location('trace_py_bridge_worker_target', BRIDGE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {BRIDGE}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_bridge()


def handle(req: dict) -> dict:
    skill_dir = str(Path(req['skill_dir']).resolve())
    out_dir = Path(req['out_dir']).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    input_file = str(Path(req['input_file']).resolve())
    mode = str(req.get('mode', 'light')).lower()
    config = req.get('config') or {}

    old_argv = sys.argv[:]
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_sys_path = sys.path[:]
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    code = 0
    error = None
    stdin_handle = None
    try:
        stdin_handle = open(input_file, 'r', encoding='utf-8')
        sys.argv = [str(BRIDGE), skill_dir, str(out_dir), mode, json.dumps(config, ensure_ascii=False), input_file]
        sys.stdin = stdin_handle
        sys.stdout = captured_out
        sys.stderr = captured_err
        MODULE.main()
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException as exc:
        code = 1
        error = f'{type(exc).__name__}: {exc}'
        captured_err.write(traceback.format_exc())
    finally:
        try:
            if stdin_handle is not None:
                stdin_handle.close()
        finally:
            sys.argv = old_argv
            sys.stdin = old_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.path[:] = old_sys_path

    return {
        'ok': code == 0,
        'exit_code': code,
        'stdout': captured_out.getvalue()[-20000:],
        'stderr': (captured_err.getvalue() or (error or ''))[-12000:],
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            response = handle(req)
        except BaseException as exc:
            response = {
                'ok': False,
                'exit_code': 1,
                'stdout': '',
                'stderr': f'{type(exc).__name__}: {exc}',
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())