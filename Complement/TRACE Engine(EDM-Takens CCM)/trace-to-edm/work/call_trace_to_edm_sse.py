"""SSE 客户端调用 trace-to-edm /api/run，正确处理流式响应。"""
import json
import time
import sys
import urllib.request
import urllib.error

TEXT_PATH = r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\work\inputs\tianshu_30news_test.txt'
API_URL = 'http://127.0.0.1:3100/api/run'
RESULT_PATH = r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\work\trace_to_edm_sse_result.json'

text = open(TEXT_PATH, encoding='utf-8').read()
# 截取前 10 条，加快速度
articles = text.split('\n\n')
text = '\n\n'.join(articles[:10])
text = text + f'\n\n[sse_call_time: {time.time()}]'

print(f'Text length: {len(text)} chars (10 news)')
print(f'POST {API_URL} (SSE)...')
start = time.time()

body = json.dumps({'text': text, 'mode': 'light'}).encode('utf-8')
req = urllib.request.Request(
    API_URL, data=body, method='POST',
    headers={
        'Content-Type': 'application/json; charset=utf-8',
        'Accept': 'text/event-stream',
        'Cache-Control': 'no-cache',
    },
)

events = []
final_payload = None

try:
    with urllib.request.urlopen(req, timeout=600) as resp:
        status = resp.status
        print(f'Status: {status}')
        buf = b''
        for chunk in iter(lambda: resp.read(1024), b''):
            buf += chunk
            # SSE 事件以 \n\n 分隔
            while b'\n\n' in buf:
                ev, buf = buf.split(b'\n\n', 1)
                ev_text = ev.decode('utf-8', errors='replace')
                # 解析 event: <type>\ndata: <json>
                ev_type = None
                ev_data = None
                for line in ev_text.split('\n'):
                    if line.startswith('event:'):
                        ev_type = line[6:].strip()
                    elif line.startswith('data:'):
                        ev_data = line[5:].strip()
                if ev_type:
                    try:
                        payload = json.loads(ev_data) if ev_data else {}
                    except Exception:
                        payload = ev_data
                    events.append({'event': ev_type, 'data': payload})
                    # 实时打印
                    elapsed = time.time() - start
                    if ev_type == 'log':
                        msg = payload.get('message', '') if isinstance(payload, dict) else str(payload)
                        if msg:
                            print(f'  [{elapsed:6.1f}s] LOG: {msg[:200]}')
                    elif ev_type == 'progress':
                        msg = payload.get('message', '') if isinstance(payload, dict) else str(payload)
                        print(f'  [{elapsed:6.1f}s] ▶ PROGRESS: {msg[:200]}')
                    elif ev_type == 'warn':
                        msg = payload.get('message', '') if isinstance(payload, dict) else str(payload)
                        print(f'  [{elapsed:6.1f}s] ⚠ WARN: {msg[:200]}')
                    elif ev_type == 'error':
                        print(f'  [{elapsed:6.1f}s] ✖ ERROR: {payload}')
                    elif ev_type == 'start':
                        print(f'  [{elapsed:6.1f}s] → START: {payload}')
                    elif ev_type == 'done':
                        print(f'  [{elapsed:6.1f}s] ✓ DONE: {payload}')
                        final_payload = payload
except urllib.error.HTTPError as e:
    print(f'HTTPError: {e.code}')
    print(e.read().decode('utf-8', errors='replace')[:1000])
    sys.exit(1)
except Exception as e:
    print(f'ERROR after {time.time()-start:.1f}s: {e}')
    sys.exit(1)

elapsed = time.time() - start
print(f'\nTotal elapsed: {elapsed:.1f}s')
print(f'Total events: {len(events)}')

with open(RESULT_PATH, 'w', encoding='utf-8') as f:
    json.dump({'events': events, 'final': final_payload, 'elapsed': elapsed}, f, ensure_ascii=False, indent=2)
print(f'Saved: {RESULT_PATH}')
