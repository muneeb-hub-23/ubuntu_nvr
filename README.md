# Luma NVR

A light-themed, self-hosted network video recorder. Next.js 16 / React frontend, FastAPI backend, SQLite configuration, encrypted camera credentials, and FFmpeg browser streaming. No cloud account required.

## Start with Docker

Requirements: Docker Engine with Compose v2 (or Docker Desktop), access from Docker to your camera network, and enough CPU for H.264 transcoding. This repository is already initialized with Git.

```sh
cp .env.example .env
# Edit .env: set a random NVR_SECRET.
# Generate a secret with: openssl rand -hex 32
docker compose up -d --build
```

On Windows PowerShell, use `Copy-Item .env.example .env`. Open **http://localhost:3000** (or your server IP) and sign in with **admin / admin** on the first installation. You must choose a new password (at least 10 characters) before accessing cameras. Passwords are salted and hashed with scrypt. Authentication uses server-side sessions and HttpOnly, SameSite cookies with a 12-hour lifetime. Sign out revokes the session; changing your password revokes all previous sessions. Use **Account** to change your password later. Login attempts are rate limited. Set `COOKIE_SECURE=true` when serving over HTTPS. Use an HTTPS reverse proxy for remote access; deploy on a trusted LAN and do not expose port 3000 directly to the internet. Only the frontend is published; the backend is on the private Compose network.

```sh
docker compose logs -f
docker compose down          # Keep all stored configuration and footage
docker compose up -d --build # Rebuild after updating source
```

The `nvr-data` named volume persists settings, cameras and recordings. Back up this volume and your `.env` together. **Keep NVR_SECRET unchanged**, because it encrypts stored camera passwords. `docker compose down -v` deletes all data.

## Connect a camera

Click **Add camera**. Enter its name, IP/hostname, protocol, port, stream path, username and password. The address field accepts a hostname or IP, without `http://` or a path. IPv4 and IPv6 are supported. Camera credentials never appear in API responses and are encrypted in SQLite.

| Protocol | Typical port | Stream path / behavior |
| --- | --- | --- |
| RTSP | 554 | Vendor-specific, e.g. `/Streaming/Channels/101`, `/cam/realmonitor?channel=1&subtype=0`, or `/stream1` |
| ONVIF | 80 or camera's ONVIF service port | Resolves the first media profile automatically; enable ONVIF on the camera and create an ONVIF user if required |
| RTMP | 1935 | e.g. `/live/stream` |
| HTTP / HTTPS | 80 / 443 | Network video sources FFmpeg can decode, including MJPEG and HLS; use the video endpoint, not a camera's HTML login page |

Open **Live view** to start the visible streams. Choose 1, 2, 4, 8, 9 or 16 divisions, page through larger camera lists, or expand the wall or a single feed to fullscreen. HLS playback uses hls.js with native HLS fallback for Safari. Streams have several seconds of latency. Audio is disabled. This is not a WebRTC/PTZ/discovery implementation.

Live video is transcoded to H.264 at up to 1280×720 / 15 fps for browser compatibility, including sources using H.265. Many concurrent feeds require substantial CPU; choose camera substreams to reduce load. Live buffers are bounded. A supervisor retries disconnected streams every 15 seconds. If the player reports an interruption, use **Retry connection**. Stop a stream in **Cameras**. Leaving Live view keeps started streams running on the server.

## Recording

Enable **Record this camera** in its setup. Video is saved in approximately 5-minute MKV segments with the original video codec; audio is omitted. Recording starts with a live stream, continues after leaving Live view, and recording-enabled cameras restart automatically after a backend restart. Use **Recordings** to refresh and download the latest 500 segments; use VLC for playback. The most recent file can still be actively written—download completed earlier segments. Camera deletion retains historical recordings.

There is **no automatic retention or disk quota** in this version. Monitor the volume's free space and archive/delete old files through the host. Recordings are under `/data/recordings/<camera-id>` in the backend volume. Stop a stream before manually modifying its active file. This implementation does not provide motion detection, event search, playback timelines, multiple users, or guaranteed archival recording.

## Time and appearance

**Settings** supports an IANA timezone (for example `Asia/Karachi`), the Docker host clock, an NTP server, or a manual date/time. NTP queries the chosen server when settings are saved; outbound UDP 123 must be available. Manual input is interpreted in the browser's local timezone. The configured offset persists and the displayed clock continues advancing. Save again to resynchronize NTP.

These settings affect the NVR display clock, not the host's OS, camera overlays, or recording filenames. Recording filenames use the container's system UTC time. Configure host and camera NTP separately if their timestamps must agree. The UI uses the requested light theme.

## Development and checks

Frontend requires Node 22+. Backend requires Python 3.12 and FFmpeg on PATH.

```sh
cd frontend
npm ci
npm run typecheck
npm run build
# Set NVR_SECRET, BACKEND_URL before npm run dev
```

```sh
cd backend
pip install -r requirements.txt httpx
python -m unittest -v test_api
# Set NVR_SECRET (32+ characters), NVR_DATA (writable directory), then:
uvicorn main:app --host 127.0.0.1 --port 8000
```

API tests cover default login, required password change, session revocation/expiration, login rate limits, camera CRUD, encrypted password handling, stream process lifecycle, recording arguments, and clock validation. After building the frontend, run `python scripts/smoke_frontend.py` from the repository root (with backend dependencies installed) for an integrated authentication check, including cookie handling and backend restart persistence. FFmpeg process creation is mocked in API tests. Actual camera/ONVIF compatibility, media playback, and Docker networking require testing on your target server with real hardware.

The admin account is initialized only when it does not exist. Rebuilds and restarts preserve its changed password in the `nvr-data` volume. The previous `NVR_USER` and `NVR_PASSWORD` environment settings are no longer used.

If a stream does not connect, verify its URL in VLC on the Docker host, confirm the stream path and ONVIF port, check credentials and camera connection limits, then retry. ONVIF discovery across subnets is not required: the supplied address is used directly. HTTPS cameras need a certificate trusted by the container. A browser cannot play RTSP directly; FFmpeg performs the conversion ([protocol documentation](https://ffmpeg.org/ffmpeg-protocols.html)). Next.js request protection uses its [Proxy convention](https://nextjs.org/docs/app/api-reference/file-conventions/proxy).
