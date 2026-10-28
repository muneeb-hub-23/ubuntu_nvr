import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
import threading
import uuid
import secrets
from collections import deque
from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

DATA = Path(os.getenv('NVR_DATA', '/data'))
DATA.mkdir(parents=True, exist_ok=True)
SECRET = os.environ['NVR_SECRET']
if len(SECRET) < 32:
    raise RuntimeError('NVR_SECRET must contain at least 32 characters')
cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest()))
db = sqlite3.connect(DATA / 'nvr.db', check_same_thread=False)
db.execute('CREATE TABLE IF NOT EXISTS cameras (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
db.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, must_change INTEGER NOT NULL)')
db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, expires REAL NOT NULL)')

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + digest

def verify_password(password, stored):
    return hmac.compare_digest(hash_password(password, stored.split(':')[0]), stored)

db.execute('INSERT OR IGNORE INTO users VALUES (?,?,1)', ('admin', hash_password('admin')))
db.commit()
login_attempts = deque()
auth_lock = threading.RLock()

def session_user(token):
    return db.execute('SELECT users.username, users.must_change FROM sessions JOIN users ON sessions.username=users.username WHERE sessions.token=? AND sessions.expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()

def new_session(username):
    token = secrets.token_urlsafe(32)
    db.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
    db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), username, time.time()+43200))
    db.commit()
    return token
workers = {}
desired = set()
worker_lock = threading.RLock()

def settings():
    row = db.execute('SELECT body FROM settings WHERE id=1').fetchone()
    return json.loads(row[0]) if row else dict(timezone='UTC', ntp_server='pool.ntp.org', mode='system', offset=0, theme='light')

def camera(cid):
    row = db.execute('SELECT body FROM cameras WHERE id=?', (cid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Camera not found')
    return json.loads(row[0])

def stop(cid):
    proc = workers.pop(cid, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

async def supervise():
    # Restore recording cameras after container restarts; retry interrupted streams.
    desired.update(json.loads(r[0])['id'] for r in db.execute('SELECT body FROM cameras') if json.loads(r[0])['record'])
    while True:
        for cid in list(desired):
            try:
                await asyncio.to_thread(start, cid)
            except Exception:
                pass
        await asyncio.sleep(15)

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(supervise())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    for cid in list(workers):
        stop(cid)

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

@app.middleware('http')
async def auth(request: Request, call_next):
    if request.url.path != '/health' and not hmac.compare_digest(request.headers.get('x-nvr-key', ''), SECRET):
        return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
    if request.method in ('POST', 'PUT', 'DELETE') and request.headers.get('sec-fetch-site') == 'cross-site':
        return JSONResponse({'detail': 'Cross-site request rejected'}, status_code=403)
    if request.url.path not in ('/health', '/auth/login'):
        user = session_user(request.headers.get('x-nvr-session', ''))
        if not user:
            return JSONResponse({'detail': 'Please sign in'}, status_code=401)
        request.state.user = user
        if user[1] and not request.url.path.startswith('/auth/'):
            return JSONResponse({'detail': 'Change your initial password before using the recorder'}, status_code=403)
    return await call_next(request)

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=500)
    new_password: str = Field(min_length=10, max_length=500)

@app.post('/auth/login')
def login(body: Login):
    with auth_lock:
        now = time.time()
        while login_attempts and login_attempts[0] < now-60:
            login_attempts.popleft()
        if len(login_attempts) >= 10:
            raise HTTPException(429, 'Too many login attempts. Try again in one minute.')
        login_attempts.append(now)
        row = db.execute('SELECT password,must_change FROM users WHERE username=?', (body.username,)).fetchone()
        dummy = db.execute('SELECT password FROM users WHERE username=?', ('admin',)).fetchone()[0]
        valid = verify_password(body.password, row[0] if row else dummy)
        if not row or not valid:
            raise HTTPException(401, 'Incorrect username or password')
        return {'token': new_session(body.username), 'username': body.username, 'must_change': bool(row[1])}

@app.get('/auth/me')
def me(request: Request):
    return {'username': request.state.user[0], 'must_change': bool(request.state.user[1])}

@app.post('/auth/logout')
def logout(request: Request):
    with auth_lock:
        db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.headers.get('x-nvr-session', '').encode()).hexdigest(),))
        db.commit()
    return {'ok': True}

@app.post('/auth/password')
def change_password(body: PasswordChange, request: Request):
    with auth_lock:
        username = request.state.user[0]
        stored = db.execute('SELECT password FROM users WHERE username=?', (username,)).fetchone()[0]
        if not verify_password(body.current_password, stored):
            raise HTTPException(400, 'Current password is incorrect')
        if verify_password(body.new_password, stored):
            raise HTTPException(422, 'Choose a different password')
        db.execute('UPDATE users SET password=?,must_change=0 WHERE username=?', (hash_password(body.new_password), username))
        db.execute('DELETE FROM sessions WHERE username=?', (username,))
        db.commit()
        return {'token': new_session(username), 'username': username, 'must_change': False}

class Camera(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=253)
    protocol: str = 'rtsp'
    port: int = Field(default=554, ge=1, le=65535)
    path: str = Field(default='/Streaming/Channels/101', max_length=1000)
    username: str = Field(default='', max_length=200)
    password: str = Field(default='', max_length=500)
    record: bool = False

    @field_validator('protocol')
    @classmethod
    def valid_protocol(cls, v):
        if v not in ('rtsp', 'rtmp', 'http', 'https', 'onvif'):
            raise ValueError('Unsupported protocol')
        return v

    @field_validator('host')
    @classmethod
    def valid_host(cls, v):
        if not re.fullmatch(r'[a-zA-Z0-9.:-]+', v):
            raise ValueError('Enter an IP address or hostname without a URL or path')
        return v

def public(c):
    result = {k: v for k, v in c.items() if k != 'password'}
    proc = workers.get(c['id'])
    playlist = DATA / 'live' / c['id'] / 'index.m3u8'
    result['status'] = 'live' if proc and proc.poll() is None and playlist.exists() and time.time()-playlist.stat().st_mtime < 20 else ('connecting' if proc and proc.poll() is None else 'idle')
    return result

@app.get('/health')
def health():
    return {'ok': True}

@app.get('/cameras')
def cameras():
    return [public(json.loads(r[0])) for r in db.execute('SELECT body FROM cameras ORDER BY rowid')]

@app.post('/cameras')
def add(body: Camera):
    c = body.model_dump()
    c['id'] = uuid.uuid4().hex
    c['password'] = cipher.encrypt(c['password'].encode()).decode()
    db.execute('INSERT INTO cameras VALUES (?,?)', (c['id'], json.dumps(c)))
    db.commit()
    return public(c)

@app.put('/cameras/{cid}')
def update(cid: str, body: Camera):
    old = camera(cid)
    c = body.model_dump()
    c.update(id=cid, password=cipher.encrypt(c['password'].encode()).decode() if c['password'] else old['password'])
    stop(cid)
    db.execute('UPDATE cameras SET body=? WHERE id=?', (json.dumps(c), cid))
    db.commit()
    return public(c)

@app.delete('/cameras/{cid}')
def delete(cid: str):
    camera(cid)
    desired.discard(cid)
    stop(cid)
    db.execute('DELETE FROM cameras WHERE id=?', (cid,))
    db.commit()
    shutil.rmtree(DATA / 'live' / cid, ignore_errors=True)
    return {'ok': True}

def source(c):
    password = cipher.decrypt(c['password'].encode()).decode()
    if c['protocol'] == 'onvif':
        from onvif import ONVIFCamera
        from zeep.transports import Transport
        device = ONVIFCamera(c['host'], c['port'], c['username'], password,
                             transport=Transport(timeout=10, operation_timeout=10), no_cache=True)
        media = device.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            raise ValueError('No ONVIF media profiles')
        uri = media.GetStreamUri({'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}, 'ProfileToken': profiles[0].token}).Uri
        parts = urlsplit(uri)
        if parts.scheme not in ('rtsp', 'http', 'https'):
            raise ValueError('Unsupported ONVIF stream')
        host = parts.hostname
        host = f'[{host}]' if ':' in host else host
        netloc = host + (f':{parts.port}' if parts.port else '')
        return urlunsplit((parts.scheme, f'{quote(c["username"], safe="")}:{quote(password, safe="")}@{netloc}', parts.path, parts.query, ''))
    host = f'[{c["host"]}]' if ':' in c['host'] else c['host']
    credentials = f'{quote(c["username"], safe="")}:{quote(password, safe="")}@' if c['username'] else ''
    return f'{c["protocol"]}://{credentials}{host}:{c["port"]}/{c["path"].lstrip("/")}'

@app.post('/cameras/{cid}/start')
def start(cid: str):
    with worker_lock:
        return start_locked(cid)

def start_locked(cid: str):
    c = camera(cid)
    desired.add(cid)
    if cid in workers and workers[cid].poll() is None:
        playlist = DATA / 'live' / cid / 'index.m3u8'
        if not playlist.exists() or time.time() - playlist.stat().st_mtime < 40:
            return {'url': f'/api/live/{cid}/index.m3u8'}
    stop(cid)
    try:
        uri = source(c)
    except Exception:
        raise HTTPException(502, 'Could not resolve stream. Check camera address, credentials and ONVIF port.')
    folder = DATA / 'live' / cid
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
    if uri.startswith('rtsp:'):
        args += ['-rtsp_transport', 'tcp', '-timeout', '15000000']
    else:
        args += ['-rw_timeout', '15000000']
    args += ['-i', uri, '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease', '-pix_fmt', 'yuv420p', '-r', '15', '-g', '30', '-sc_threshold', '0', '-f', 'hls', '-hls_time', '2', '-hls_list_size', '6', '-hls_flags', 'delete_segments+temp_file', '-hls_segment_filename', str(folder / 'segment%09d.ts'), str(folder / 'index.m3u8')]
    if c['record']:
        recordings = DATA / 'recordings' / cid
        recordings.mkdir(parents=True, exist_ok=True)
        args += ['-map', '0:v:0', '-an', '-c:v', 'copy', '-f', 'segment', '-segment_time', '300', '-reset_timestamps', '1', '-strftime', '1', str(recordings / '%Y%m%d-%H%M%S.mkv')]
    workers[cid] = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {'url': f'/api/live/{cid}/index.m3u8'}

@app.post('/cameras/{cid}/stop')
def stop_camera(cid: str):
    camera(cid)
    with worker_lock:
        desired.discard(cid)
        stop(cid)
    return {'ok': True}

@app.get('/live/{cid}/{filename}')
def live(cid: str, filename: str):
    camera(cid)
    if not re.fullmatch(r'(index\.m3u8|segment[0-9]+\.ts)', filename):
        raise HTTPException(404)
    path = DATA / 'live' / cid / filename
    if not path.is_file():
        raise HTTPException(404, 'Stream warming up or camera unavailable')
    return FileResponse(path, media_type='application/vnd.apple.mpegurl' if filename.endswith('m3u8') else 'video/mp2t', headers={'Cache-Control': 'no-store'})

@app.get('/recordings')
def recordings():
    return [{'camera_id': p.parent.name, 'filename': p.name, 'bytes': p.stat().st_size} for p in sorted((DATA / 'recordings').glob('*/*.mkv'), reverse=True)][:500]

@app.get('/recordings/{cid}/{filename}')
def download(cid: str, filename: str):
    if not re.fullmatch('[a-f0-9]{32}', cid) or not re.fullmatch(r'[0-9]{8}-[0-9]{6}\.mkv', filename):
        raise HTTPException(404)
    path = DATA / 'recordings' / cid / filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=filename)

class Settings(BaseModel):
    timezone: str = 'UTC'
    ntp_server: str = Field(default='pool.ntp.org', min_length=1, max_length=253)
    mode: str = 'system'
    manual_time: float | None = None
    theme: str = 'light'

@app.get('/settings')
def get_settings():
    s = settings()
    return {**s, 'now': time.time() + s['offset']}

@app.put('/settings')
def set_settings(body: Settings):
    try:
        ZoneInfo(body.timezone)
    except Exception:
        raise HTTPException(422, 'Invalid IANA timezone')
    if body.mode not in ('system', 'ntp', 'manual') or body.theme != 'light':
        raise HTTPException(422, 'Invalid clock mode or theme')
    offset = 0
    if body.mode == 'ntp':
        try:
            import ntplib
            offset = ntplib.NTPClient().request(body.ntp_server, version=3, timeout=5).offset
        except Exception:
            raise HTTPException(502, 'NTP server unreachable; settings were not changed')
    if body.mode == 'manual':
        if body.manual_time is None or not 0 < body.manual_time < 32503680000:
            raise HTTPException(422, 'A valid manual date/time is required')
        offset = body.manual_time - time.time()
    s = {**body.model_dump(exclude={'manual_time'}), 'offset': offset}
    db.execute('INSERT OR REPLACE INTO settings VALUES (1,?)', (json.dumps(s),))
    db.commit()
    return get_settings()
