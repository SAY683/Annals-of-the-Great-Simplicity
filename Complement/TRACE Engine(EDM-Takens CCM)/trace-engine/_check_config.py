import urllib.request, json
try:
    with urllib.request.urlopen('http://localhost:3030/api/config', timeout=5) as r:
        data = json.loads(r.read().decode('utf-8'))
        print('config OK')
        print('modes:', list(data.get('modes', {}).keys()))
        print('llama available:', data.get('llamaWorker', {}).get('available'))
except Exception as e:
    print('config FAIL:', e)

try:
    with urllib.request.urlopen('http://localhost:3030/api/health', timeout=5) as r:
        data = json.loads(r.read().decode('utf-8'))
        print('health OK:', data.get('status'))
except Exception as e:
    print('health FAIL:', e)
