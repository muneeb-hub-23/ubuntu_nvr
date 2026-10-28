"""Check the built standalone server's HTTP authentication boundaries."""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request

root = Path(__file__).resolve().parent.parent
env = {**os.environ, 'PORT': '3307', 'HOSTNAME': '127.0.0.1',
       'NVR_USER': 'smoke', 'NVR_PASSWORD': 'temporary-smoke-password',
       'NVR_SECRET': 'temporary-smoke-secret-over-32-characters'}
process = subprocess.Popen([shutil.which('node'), str(root / 'frontend/.next/standalone/server.js')],
                           cwd=root / 'frontend', env=env)
base = 'http://127.0.0.1:3307'
try:
    for attempt in range(30):
        try:
            urllib.request.urlopen(base, timeout=1)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                break
            raise
        except urllib.error.URLError:
            time.sleep(0.5)
    else:
        raise RuntimeError('Server did not become ready')
    for path in ('/', '/api/cameras', '/api/settings', '/api/recordings'):
        try:
            urllib.request.urlopen(base + path, timeout=5)
            raise AssertionError('Anonymous request succeeded: ' + path)
        except urllib.error.HTTPError as error:
            assert error.code == 401, (path, error.code)
    auth = base64.b64encode(b'smoke:temporary-smoke-password').decode()
    response = urllib.request.urlopen(urllib.request.Request(base, headers={'Authorization': 'Basic ' + auth}), timeout=15)
    assert response.status == 200
    assert 'Camera wall' in response.read().decode()
    print('PASS: authenticated page 200; anonymous page and API requests 401')
finally:
    process.terminate()
    process.wait(timeout=10)
