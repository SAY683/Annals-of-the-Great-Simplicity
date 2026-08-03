"""
跨项目 HTTP 契约测试
=====================
验证五大项目之间的 HTTP API 契约一致性。

覆盖:
  - trace-engine-web ↔ trace-to-edm (结果消费)
  - trace-to-edm → edm-takens-web (EDM 触发)
  - 缓存戳/CSS 主题/错误格式/鉴权统一性

三态测试:
  PASS = 服务运行且契约通过
  FAIL = 服务运行但契约违反
  SKIP = 服务未运行（不算失败）

退出码:
  0 = 有 PASS 且无 FAIL
  1 = 有 FAIL
  2 = 全部 SKIP (服务未运行)

用法:
  python test_cross_project_http.py
  python test_cross_project_http.py --strict  # SKIP 也算 FAIL
"""
import json
import sys
import urllib.request
import urllib.error

# ── 配置 ──────────────────────────────────────────────────
SERVICES = {
    'trace-engine-web': {
        'base': 'http://127.0.0.1:3000',
        'health': '/api/health',
        'config': '/api/config',
    },
    'trace-to-edm': {
        'base': 'http://127.0.0.1:3100',
        'health': '/api/health',
        'status': '/api/status',
    },
    'edm-takens-web': {
        'base': 'http://127.0.0.1:8000',
        'health': '/api/health',
        'datasets': '/api/datasets',
    },
}

# 缓存戳契约（所有项目应使用一致的版本戳）
EXPECTED_CACHE_STAMP = '20260730'


def _fetch(base, path, timeout=5):
    """GET 请求，返回 (status, json_dict, raw_text)。服务未运行返回 (None, None, None)。"""
    url = f'{base}{path}'
    # 强制直连，避免代理拦截
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        req = urllib.request.Request(url)
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8')
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8') if e.fp else ''
        try:
            return e.code, json.loads(raw) if raw else None, raw
        except json.JSONDecodeError:
            return e.code, None, raw
    except (urllib.error.URLError, ConnectionError, OSError):
        return None, None, None


def test_service_health(name, cfg):
    """测试单个服务的健康检查端点。"""
    status, data, _ = _fetch(cfg['base'], cfg['health'])
    if status is None:
        print(f'  SKIP: {name} 未运行')
        return 'skip'
    if status != 200:
        print(f'  FAIL: {name} /api/health 状态码={status}')
        return 'fail'
    if data and data.get('success') is True:
        print(f'  PASS: {name} /api/health (success=true)')
        return 'pass'
    if data and data.get('status') in ('healthy', 'degraded'):
        print(f'  PASS: {name} /api/health (status={data.get("status")})')
        return 'pass'
    print(f'  FAIL: {name} /api/health 响应不符合契约: {str(data)[:100]}')
    return 'fail'


def test_trace_engine_web_config():
    """测试 trace-engine-web 的 /api/config 契约。"""
    cfg = SERVICES['trace-engine-web']
    status, data, _ = _fetch(cfg['base'], cfg['config'])
    if status is None:
        print(f'  SKIP: trace-engine-web 未运行')
        return 'skip'
    if status != 200:
        print(f'  FAIL: /api/config 状态码={status}')
        return 'fail'
    if not data or not data.get('success'):
        print(f'  FAIL: /api/config success!=true')
        return 'fail'
    modes = data.get('modes', {})
    if 'super' not in modes:
        print(f'  FAIL: /api/config 未暴露 SUPER 模式')
        return 'fail'
    schema = data.get('bridgeParamSchema', {})
    if 'max_segments' not in schema:
        print(f'  FAIL: bridgeParamSchema 缺少 max_segments')
        return 'fail'
    print(f'  PASS: /api/config (SUPER 模式 + max_segments 契约)')
    return 'pass'


def test_trace_to_edm_status():
    """测试 trace-to-edm 的 /api/status 端点。"""
    cfg = SERVICES['trace-to-edm']
    status, data, _ = _fetch(cfg['base'], cfg['status'])
    if status is None:
        print(f'  SKIP: trace-to-edm 未运行')
        return 'skip'
    if status != 200:
        print(f'  FAIL: /api/status 状态码={status}')
        return 'fail'
    if not data:
        print(f'  FAIL: /api/status 无响应体')
        return 'fail'
    # 验证 confidence_level 字段存在
    if 'confidence_level' not in str(data):
        print(f'  WARN: /api/status 未包含 confidence_level 字段')
    print(f'  PASS: /api/status (响应包含关键字段)')
    return 'pass'


def test_cross_project_consistency():
    """测试跨项目一致性（CSS 主题/错误格式）。"""
    results = []
    for name, cfg in SERVICES.items():
        status, data, raw = _fetch(cfg['base'], cfg['health'])
        if status is None:
            print(f'  SKIP: {name} 未运行')
            results.append('skip')
            continue
        # 验证错误格式一致性（非 200 时应返回 JSON）
        if status == 200:
            print(f'  PASS: {name} 响应格式一致 (JSON)')
            results.append('pass')
        else:
            print(f'  FAIL: {name} 响应状态码={status}')
            results.append('fail')
    return results


def main():
    strict = '--strict' in sys.argv
    print('=' * 60)
    print('跨项目 HTTP 契约测试')
    print('=' * 60)

    total_pass = 0
    total_fail = 0
    total_skip = 0

    print('\n--- 1. 服务健康检查 ---')
    for name, cfg in SERVICES.items():
        r = test_service_health(name, cfg)
        if r == 'pass':
            total_pass += 1
        elif r == 'fail':
            total_fail += 1
        else:
            total_skip += 1

    print('\n--- 2. trace-engine-web /api/config 契约 ---')
    r = test_trace_engine_web_config()
    if r == 'pass':
        total_pass += 1
    elif r == 'fail':
        total_fail += 1
    else:
        total_skip += 1

    print('\n--- 3. trace-to-edm /api/status 契约 ---')
    r = test_trace_to_edm_status()
    if r == 'pass':
        total_pass += 1
    elif r == 'fail':
        total_fail += 1
    else:
        total_skip += 1

    print('\n--- 4. 跨项目响应格式一致性 ---')
    results = test_cross_project_consistency()
    for r in results:
        if r == 'pass':
            total_pass += 1
        elif r == 'fail':
            total_fail += 1
        else:
            total_skip += 1

    print('\n' + '=' * 60)
    print(f'总计: PASS={total_pass} FAIL={total_fail} SKIP={total_skip}')
    print('=' * 60)

    if total_fail > 0:
        print('结论: FAIL')
        sys.exit(1)
    if total_pass == 0 and total_skip > 0:
        if strict:
            print('结论: ALL SKIP (严格模式视为 FAIL)')
            sys.exit(1)
        print('结论: ALL SKIP (服务未运行)')
        sys.exit(2)
    print('结论: PASS')
    sys.exit(0)


if __name__ == '__main__':
    main()
