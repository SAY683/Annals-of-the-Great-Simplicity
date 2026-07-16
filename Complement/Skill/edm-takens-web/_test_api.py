import urllib.request
import json
url = 'http://127.0.0.1:8000/api/analyze'
boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = (
    '------WebKitFormBoundary7MA4YWxkTrZu0gW\r\n'
    'Content-Disposition: form-data; name="filename"\r\n\r\n'
    'yinshen_ji_vowel.csv\r\n'
    '------WebKitFormBoundary7MA4YWxkTrZu0gW\r\n'
    'Content-Disposition: form-data; name="target_col"\r\n\r\n'
    '太姬\r\n'
    '------WebKitFormBoundary7MA4YWxkTrZu0gW\r\n'
    'Content-Disposition: form-data; name="variables"\r\n\r\n'
    '美姬,希姬,祈姬,妙姬\r\n'
    '------WebKitFormBoundary7MA4YWxkTrZu0gW\r\n'
    'Content-Disposition: form-data; name="auto_fix"\r\n\r\n'
    'true\r\n'
    '------WebKitFormBoundary7MA4YWxkTrZu0gW--\r\n'
)
req = urllib.request.Request(url, data=body.encode('utf-8'), method='POST')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
try:
    with urllib.request.urlopen(req, timeout=300) as res:
        data = json.loads(res.read().decode('utf-8'))
        print(json.dumps(data.get('summary', {}), ensure_ascii=False, indent=2))
        print('task_id:', data.get('task_id'))
        print('images:', data.get('images'))
        print('error:', data.get('error'))
except Exception as e:
    print('ERROR:', e)
