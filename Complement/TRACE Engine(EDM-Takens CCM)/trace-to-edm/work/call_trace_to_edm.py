"""调用 trace-to-edm 的 /api/run (Mode A 文本管线)，验证数据流管道字段契约。"""
import json
import time
import sys
import urllib.request
import urllib.error

TEXT_PATH = r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\work\inputs\tianshu_30news_test.txt'
API_URL = 'http://127.0.0.1:3100/api/run'
RESULT_PATH = r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\work\trace_to_edm_run_result.json'

text = open(TEXT_PATH, encoding='utf-8').read()
text = text + f'\n\n[trace_to_edm_call_time: {time.time()}]'

print(f'Text length: {len(text)} chars')
print(f'POST {API_URL} ...')
start = time.time()

body = json.dumps({'text': text, 'mode': 'light'}).encode('utf-8')
req = urllib.request.Request(
    API_URL, data=body, method='POST',
    headers={'Content-Type': 'application/json; charset=utf-8'},
)

try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode('utf-8')
        status = resp.status
except urllib.error.HTTPError as e:
    raw = e.read().decode('utf-8')
    status = e.code
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)

elapsed = time.time() - start
print(f'Status: {status} | Elapsed: {elapsed:.1f}s')

try:
    j = json.loads(raw)
except Exception:
    print(f'Non-JSON response (first 500 chars): {raw[:500]}')
    sys.exit(1)

with open(RESULT_PATH, 'w', encoding='utf-8') as f:
    json.dump(j, f, ensure_ascii=False, indent=2)
print(f'Full result saved: {RESULT_PATH}')

# 打印关键字段
print('\n=== TOP-LEVEL KEYS ===')
for k in j.keys():
    v = j[k]
    if isinstance(v, (dict, list)):
        print(f'  {k}: {type(v).__name__} (len={len(v) if hasattr(v, "__len__") else "n/a"})')
    else:
        print(f'  {k}: {v}')

# 检查 trace_id / job_id / status / csv_path
print('\n=== FIELD CONTRACT ===')
for f in ['job_id', 'trace_id', 'status', 'csv_path', 'csv_url', 'error', 'mode']:
    print(f'  {f}: {j.get(f, "<<MISSING>>")}')

# 若有 trajectory / summary
if 'trajectory' in j:
    print(f'\n=== TRAJECTORY (keys) ===')
    traj = j['trajectory']
    if isinstance(traj, dict):
        for k in traj.keys():
            print(f'  {k}')
if 'summary' in j:
    print(f'\n=== SUMMARY (first 300 chars) ===')
    s = j['summary']
    if isinstance(s, str):
        print(s[:300])
    else:
        print(json.dumps(s, ensure_ascii=False)[:300])
