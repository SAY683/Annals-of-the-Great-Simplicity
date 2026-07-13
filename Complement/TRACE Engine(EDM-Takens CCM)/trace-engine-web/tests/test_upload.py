import http.client
import uuid
import json

boundary = uuid.uuid4().hex
parts = []
parts.append(f'--{boundary}'.encode())
parts.append(b'Content-Disposition: form-data; name="file"; filename="sample_input.txt"')
parts.append(b'Content-Type: text/plain')
parts.append(b'')
with open('sample_input.txt', 'rb') as f:
    parts.append(f.read())
parts.append(f'--{boundary}--'.encode())
body = b'\r\n'.join(parts)

conn = http.client.HTTPConnection('localhost', 3006, timeout=60)
conn.request('POST', '/api/analyze-file', body=body,
             headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
resp = conn.getresponse()
data = resp.read().decode('utf-8')
print('status', resp.status)
obj = json.loads(data)
print('success', obj.get('success'))
print('id', obj.get('data', {}).get('id'))
