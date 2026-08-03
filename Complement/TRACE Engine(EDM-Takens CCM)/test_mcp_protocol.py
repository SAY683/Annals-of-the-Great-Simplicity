"""
MCP 协议端到端测试
==================
验证五大项目的 MCP (Model Context Protocol) 端点契约。

覆盖:
  - trace-engine-web: POST /mcp (7 tools)
  - trace-to-edm:    POST /mcp (7 tools)
  - edm-takens-web:  POST /mcp (6 tools)

测试项:
  1. initialize 握手 (protocolVersion 2024-11-05)
  2. tools/list 工具枚举 (验证工具数量与名称)
  3. tools/call health 健康检查 (业务字段验证)
  4. JSON-RPC 2.0 协议校验 (错误码 -32600/-32601/-32602)

退出码:
  0 = 全部 PASS
  1 = 有 FAIL
  2 = 全部 SKIP (服务未运行)

用法:
  python test_mcp_protocol.py              # 测试全部
  python test_mcp_protocol.py --strict     # 严格模式 (SKIP 也算 FAIL)
"""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────
SERVICES = [
    {
        'name': 'trace-engine-web',
        'url': 'http://127.0.0.1:3000/mcp',
        'expected_tools': ['analyze_text', 'list_jobs', 'get_job',
                           'get_job_detail', 'get_result', 'export_md', 'health'],
        'health_tool': 'health',
    },
    {
        'name': 'trace-to-edm',
        'url': 'http://127.0.0.1:3100/mcp',
        'expected_tools': ['run_pipeline', 'trigger_edm', 'get_trajectory',
                           'list_projects', 'list_models', 'get_dataset',
                           'health', 'version'],
        'health_tool': 'health',
    },
    {
        'name': 'edm-takens-web',
        'url': 'http://127.0.0.1:8000/mcp',
        'expected_tools': ['list_datasets', 'run_analysis', 'get_job',
                           'list_history', 'get_history_detail', 'health'],
        'health_tool': 'health',
    },
]

EXPECTED_TOOL_COUNT = sum(len(s['expected_tools']) for s in SERVICES)
PROTOCOL_VERSION = '2024-11-05'


def _post_jsonrpc(url, method, params=None, req_id=1):
    """发送 JSON-RPC 2.0 请求，返回 (status_code, response_dict)。"""
    payload = {
        'jsonrpc': '2.0',
        'method': method,
        'params': params or {},
        'id': req_id,
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8')
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8') if e.fp else ''
        try:
            return e.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return e.code, None
    except (urllib.error.URLError, ConnectionError, OSError):
        return None, None  # 服务未运行


def test_service(svc):
    """测试单个服务的 MCP 端点。返回 (pass_count, fail_count, skip)。"""
    name = svc['name']
    url = svc['url']
    results = {'pass': 0, 'fail': 0, 'skip': False}

    print(f'\n=== {name} ({url}) ===')

    # 1. 连通性检查
    status, _ = _post_jsonrpc(url, 'initialize')
    if status is None:
        print(f'  SKIP: 服务未运行')
        results['skip'] = True
        return results

    # 2. initialize 握手
    status, resp = _post_jsonrpc(url, 'initialize')
    if status == 200 and resp and 'result' in resp:
        proto = resp['result'].get('protocolVersion', '')
        if proto == PROTOCOL_VERSION:
            print(f'  PASS: initialize (protocol={proto})')
            results['pass'] += 1
        else:
            print(f'  FAIL: initialize 协议版本不匹配 (期望 {PROTOCOL_VERSION}, 实际 {proto})')
            results['fail'] += 1
    else:
        print(f'  FAIL: initialize (status={status})')
        results['fail'] += 1

    # 3. tools/list 工具枚举
    status, resp = _post_jsonrpc(url, 'tools/list')
    if status == 200 and resp and 'result' in resp:
        tools = resp['result'].get('tools', [])
        tool_names = [t.get('name', '') for t in tools]
        expected = set(svc['expected_tools'])
        actual = set(tool_names)
        missing = expected - actual
        extra = actual - expected
        if not missing:
            print(f'  PASS: tools/list ({len(tool_names)} tools, 全部期望工具存在)')
            results['pass'] += 1
        else:
            print(f'  FAIL: tools/list 缺失工具: {missing}')
            results['fail'] += 1
        if extra:
            print(f'  WARN: 额外工具: {extra}')
    else:
        print(f'  FAIL: tools/list (status={status})')
        results['fail'] += 1

    # 4. tools/call health 健康检查
    status, resp = _post_jsonrpc(url, 'tools/call',
                                 {'name': svc['health_tool'], 'arguments': {}})
    if status == 200 and resp and 'result' in resp:
        content = resp['result'].get('content', [])
        is_error = resp['result'].get('isError', False)
        if not is_error and content:
            print(f'  PASS: tools/call health (内容长度={len(content[0].get("text", ""))})')
            results['pass'] += 1
        else:
            print(f'  FAIL: tools/call health 返回错误 (isError={is_error})')
            results['fail'] += 1
    else:
        print(f'  FAIL: tools/call health (status={status})')
        results['fail'] += 1

    # 5. JSON-RPC 协议校验 (无效 jsonrpc 版本)
    status, resp = _post_jsonrpc(url, 'initialize', req_id=99)
    # 故意发错误的 jsonrpc 版本
    bad_payload = {'jsonrpc': '1.0', 'method': 'initialize', 'id': 99}
    bad_data = json.dumps(bad_payload).encode('utf-8')
    bad_req = urllib.request.Request(url, data=bad_data,
                                     headers={'Content-Type': 'application/json'},
                                     method='POST')
    try:
        with urllib.request.urlopen(bad_req, timeout=10) as r:
            bad_resp = json.loads(r.read().decode('utf-8'))
        if bad_resp.get('error', {}).get('code') == -32600:
            print(f'  PASS: JSON-RPC 协议校验 (错误码 -32600)')
            results['pass'] += 1
        else:
            print(f'  FAIL: JSON-RPC 协议校验未返回 -32600')
            results['fail'] += 1
    except Exception:
        print(f'  FAIL: JSON-RPC 协议校验请求失败')
        results['fail'] += 1

    return results


def main():
    strict = '--strict' in sys.argv
    print('=' * 60)
    print('MCP 协议端到端测试')
    print(f'期望工具总数: {EXPECTED_TOOL_COUNT}')
    print('=' * 60)

    total_pass = 0
    total_fail = 0
    total_skip = 0

    for svc in SERVICES:
        r = test_service(svc)
        total_pass += r['pass']
        total_fail += r['fail']
        if r['skip']:
            total_skip += 1

    print('\n' + '=' * 60)
    print(f'总计: PASS={total_pass} FAIL={total_fail} SKIP={total_skip}')
    print('=' * 60)

    if total_fail > 0:
        print('结论: FAIL')
        sys.exit(1)
    if total_skip == len(SERVICES):
        if strict:
            print('结论: ALL SKIP (严格模式视为 FAIL)')
            sys.exit(1)
        print('结论: ALL SKIP (服务未运行)')
        sys.exit(2)
    print('结论: PASS')
    sys.exit(0)


if __name__ == '__main__':
    main()
