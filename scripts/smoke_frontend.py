"""Exercise sign-in and session cookies through Next.js and FastAPI together."""
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

root = Path(__file__).resolve().parent.parent
test_root = root / '.test-data'
test_root.mkdir(exist_ok=True)
temporary = tempfile.TemporaryDirectory(dir=test_root)
env = {**os.environ, 'PORT': '3307', 'HOSTNAME': '127.0.0.1',
       'BACKEND_URL': 'http://127.0.0.1:8017', 'NVR_DATA': temporary.name,
       'NVR_SECRET': 'temporary-smoke-secret-over-32-characters', 'COOKIE_SECURE': 'false'}
if (root / '.test-deps').exists():
    env['PYTHONPATH'] = str(root / '.test-deps')
backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8017'], cwd=root / 'backend', env=env)
process = None
base = 'http://127.0.0.1:3307'
jar = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def request(path, data=None):
    req = urllib.request.Request(base+path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type':'application/json'})
    try:
        response = client.open(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    return response.code, response.read().decode()

def wait(url):
    for _ in range(40):
        try:
            urllib.request.urlopen(url, timeout=5)
            return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(.5)
    raise RuntimeError('Server did not become ready: '+url)

try:
    wait(env['BACKEND_URL']+'/health')
    process = subprocess.Popen([shutil.which('node'), str(root / 'frontend/.next/standalone/server.js')], cwd=root / 'frontend', env=env)
    wait(base+'/login')
    assert 'Welcome back' in request('/')[1]
    for path in ('/api/cameras', '/api/settings', '/api/recordings'):
        assert request(path)[0] == 401, path
    status, body = request('/api/auth/login', {'username':'admin','password':'admin'})
    assert status == 200 and json.loads(body)['must_change']
    assert 'token' not in json.loads(body)
    cookie = next(iter(jar))
    assert cookie.name == 'nvr_session' and cookie.has_nonstandard_attr('HttpOnly')
    assert request('/api/cameras')[0] == 403
    status, body = request('/api/auth/password', {'current_password':'admin','new_password':'new-smoke-password'})
    assert status == 200 and not json.loads(body)['must_change']
    assert 'Camera wall' in request('/')[1]
    assert request('/api/cameras')[0] == 200
    backend.terminate()
    backend.wait(timeout=10)
    backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8017'], cwd=root / 'backend', env=env)
    wait(env['BACKEND_URL']+'/health')
    assert request('/api/cameras')[0] == 200
    assert request('/api/auth/logout', {})[0] == 200
    assert not list(jar)
    assert request('/api/cameras')[0] == 401
    assert request('/api/auth/login', {'username':'admin','password':'admin'})[0] == 401
    assert request('/api/auth/login', {'username':'admin','password':'new-smoke-password'})[0] == 200
    print('PASS: default login, password change, HttpOnly cookie, protected page/API, restart persistence, logout and changed-password login')
finally:
    for child in (process, backend):
        if child:
            child.terminate()
            child.wait(timeout=10)
    temporary.cleanup()
