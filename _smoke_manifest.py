import requests
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

URL = 'http://127.0.0.1:8124'

print('=== GET /api/v1/areas/alimentacion/manifest ===')
r = requests.get(f'{URL}/api/v1/areas/alimentacion/manifest')
print(f'Status: {r.status_code}')
try:
    data = r.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f'(no JSON: {e})')

print()
print('=== GET /static/areas/alimentacion/frontend/components/Sidebar.js ===')
r = requests.get(f'{URL}/static/areas/alimentacion/frontend/components/Sidebar.js')
ct = r.headers.get('content-type')
print(f'Status: {r.status_code}')
print(f'Content-Type: {ct}')
print(f'Body (first 200 chars): {r.text[:200]}')

print()
print('=== GET /api/v1/areas/inexistente/manifest (debe 404) ===')
r = requests.get(f'{URL}/api/v1/areas/inexistente/manifest')
print(f'Status: {r.status_code}')
print(f'Body: {r.text[:200]}')

print()
print('=== GET /api/v1/areas (sigue funcionando) ===')
r = requests.get(f'{URL}/api/v1/areas')
print(f'Status: {r.status_code}')
print(f'Body: {r.json()}')

