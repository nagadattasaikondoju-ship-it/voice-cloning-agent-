# Intelligence Designed To Evolve

Consent-verified AI voice cloning and text-to-speech. A user can only clone their **own** voice: the
server issues a random phrase, the user reads it aloud, and the Rust API refuses to create a clone
until Whisper's transcript of that recording matches the phrase.

- **Rust (Axum) API**: auth, consent, uploads, ownership checks, audit log
- **Python worker**: runs clone and speech jobs from Redis on one of three engines
- **Whisper speech pipeline** (FastAPI + faster-whisper): verifies spoken consent and transcribes F5 reference clips
- **Static dashboard** (HTML/CSS/vanilla JS)

---

## Architecture

```
 Browser  http://localhost:5500  (index.html + frontend/dashboard.html)
    │  JWT (Authorization: Bearer), multipart audio uploads
    ▼
 Rust API  :8080  ──────────────►  speech_pipeline  :8000
    │                                POST /api/v1/transcribe  (faster-whisper)
    │                                ▲ consent check: transcript vs phrase, word-level match ≥ 75%
    ├──► PostgreSQL   users, consents, voice_samples, voice_clones,
    │                 speech_jobs, generated_audio, audit_logs
    ├──► Redis lists  voice_clone_jobs · speech_jobs · delete_voice_jobs   (plain JSON)
    └──► private_storage/  samples/ consents/ references/ generated/   (shared volume)
                   │
                   ▼
 Python worker (BRPOP) ──► engine:
                             f5          F5-TTS Hugging Face Space (free, zero-shot)
                             minimax     MiniMax voice_clone + t2a_v2 (MINIMAX_API_KEY)
                             elevenlabs  ElevenLabs Instant Voice Clone (ELEVENLABS_API_KEY)
                   └──► output normalized to MP3 → generated_audio row → status 'ready' / 'failed'
```

### Consent and cloning flow

1. `POST /api/consents`: the server generates a phrase with three random code words.
2. The user records the phrase in the browser, then `POST /api/consents/:id/verify` uploads it.
3. The API sends the clip to the speech pipeline, scores the transcript against the phrase
   (word edit distance; tolerant of small mishearings and British/American spellings), and sets
   `verified` only if the score is at least `CONSENT_MATCH_THRESHOLD`. Each phrase allows 5 attempts.
4. `POST /api/voice-samples` stores the sample. `POST /api/voice-clones` (requires a verified consent you own)
   queues the clone job, and the dashboard polls until `ready` or `failed` (with the reason).
5. `POST /api/speech/generate` queues synthesis, and the dashboard polls `/api/speech/jobs/:id`.
   Audio is served only to its owner (`GET /api/audio/:id` with the JWT). The dashboard plays it from a blob URL.

### Engines

| Engine | Cost | Needs | Notes |
|---|---|---|---|
| `f5` | Free | nothing (`HF_TOKEN` recommended) | Zero-shot through the public `mrfakename/E2-F5-TTS` Space. The worker trims the sample to 12 s and transcribes it with Whisper as the reference text. Anonymous use hits ZeroGPU quotas quickly, so set `HF_TOKEN`. Speed, volume and pitch are not supported. |
| `minimax` | Paid | `MINIMAX_API_KEY` | `speech-2.8-hd`. Supports speed, volume and pitch. Samples should be 10 s–5 min. |
| `elevenlabs` | Paid plan | `ELEVENLABS_API_KEY` | Instant Voice Clone + `eleven_multilingual_v2`. Speed 0.7–1.2. |

The worker checks each engine at startup and every 10 minutes (`worker-python/health.py`) and publishes the result.
An engine that fails its check is shown as unavailable in the dashboard, with the reason, and the API rejects it.

---

## Quick start (Docker)

```bash
cp .env.example .env
```

Set `JWT_SECRET` in `.env` (required). Optionally add `HF_TOKEN`, `MINIMAX_API_KEY` or `ELEVENLABS_API_KEY`. Generate a secret with:

```bash
openssl rand -hex 32
```

Then start everything:

```bash
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:5500 | Landing page |
| http://localhost:5500/frontend/dashboard.html | Voice Studio (create an account, then clone) |
| http://localhost:8080/api/health | API health (DB, Redis, Whisper) |
| http://localhost:8000/docs | Speech pipeline API docs |

The first consent check downloads the Whisper model (`WHISPER_MODEL_CPU`, default `base`), which can take a minute.

## Local development (without Docker)

Needs Rust 1.89+, Python 3.11+, PostgreSQL 15+, Redis 7+ and `ffmpeg`.

```bash
createdb voiceclone
```

Speech pipeline (port 8000):

```bash
cd speech_pipeline && python -m venv .venv && . .venv/bin/activate
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Rust API (port 8080). Migrations run automatically on start:

```bash
cd backend-rust && cp .env.example .env    # set JWT_SECRET
cargo run
```

Worker:

```bash
cd worker-python && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
python main.py
```

Static frontend (port 5500), from the repo root:

```bash
python -m http.server 5500
```

The dashboard calls `http://localhost:8080` by default (`frontend/config.js`). To point it elsewhere,
run `localStorage.setItem("api_base_url", "https://api.example.com")` in the browser console.

### Tests

```bash
cd backend-rust && cargo test
```

```bash
cd speech_pipeline && pytest
```

---

## Troubleshooting: "I added API keys but cloning still fails"

Open **Settings → Voice Engines** in the dashboard. Each engine shows whether it works and, if not, why. The
same check runs from a terminal:

```bash
docker compose exec worker-python python health.py
```

| Symptom | Cause | Fix |
|---|---|---|
| Engine shows "unavailable", "worker is not running" | `worker-python` isn't running, so no job ever runs | Start it; check `docker compose logs worker-python` |
| Key set but engine "not configured" | The key is in the wrong `.env`. Docker reads only the **root** `.env` | Put keys in `./.env` and run `docker compose up -d` again |
| MiniMax `1004` | Wrong key, or the key's region doesn't match the URL | Set `MINIMAX_BASE_URL` (`api.minimax.io` international, `api.minimaxi.com` China) |
| MiniMax `2038` | Account not verified for cloning | Complete verification at platform.minimax.io |
| MiniMax `1008` | No balance (cloning and speech are paid) | Top up the MiniMax account |
| MiniMax `2013` | Sample under 10 s or over 5 min | Upload 10–60 s of clean speech |
| MiniMax voice disappears | MiniMax deletes cloned voices unused for 7 days | Generate speech with it soon after cloning |
| ElevenLabs "plan does not include Instant Voice Cloning" | Free plan | Starter plan or above |
| ElevenLabs "missing permissions" | Restricted API key | New key with Voices (write), Text to Speech, User (read) |
| F5 "GPU quota is used up" | Anonymous ZeroGPU limit on the public Space | Set `HF_TOKEN` (free); Hugging Face Pro raises the quota; or use a paid engine |
| Consent "speech recognition unavailable" | `speech-pipeline` is down or still downloading Whisper | Check `docker compose logs speech-pipeline` |
| Dashboard says "Cannot reach the API" | Opened as `file://`, or from an origin not in `ALLOWED_ORIGINS` | Open http://localhost:5500 |
| Microphone does not work | Browsers allow the mic only on `localhost` or HTTPS | Use localhost, or HTTPS when deployed |

## Scripts from files or audio

In **Text to Speech**, **Load script or audio** fills the script box from `.txt`, `.md`, `.srt` or `.vtt`.
Audio (mp3, m4a, wav, webm, ogg) is transcribed with Whisper (`POST /api/transcribe`), so an existing recording can
be re-spoken in a cloned voice.

---

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | DB / Redis / speech-pipeline status |
| GET | `/api/engines` | Engines and whether each is configured |
| POST | `/api/auth/register` · `/api/auth/login` | `{email, password}` → `{token, user}` (JWT, 24 h) |
| POST | `/api/auth/logout` · GET `/api/auth/me` | |
| POST | `/api/consents` | Issues a consent phrase |
| POST | `/api/consents/:id/verify` | multipart `audio` → `{verified, transcript, match_score, threshold, attempts_remaining}` |
| GET | `/api/consents` | |
| POST / GET | `/api/voice-samples` | multipart `audio` (mp3/m4a/wav/webm/ogg, ≤20 MB) + `duration` |
| POST | `/api/voice-clones` | `{consent_id, sample_id, display_name, engine}` |
| GET | `/api/voice-clones` · `/api/voice-clones/:id` | |
| DELETE | `/api/voice-clones/:id` | Soft-deletes and removes the voice from the provider |
| POST | `/api/speech/generate` | `{voice_clone_id, text, speed?, volume?, pitch?}` → job |
| GET | `/api/speech/jobs/:id` · `/api/speech/history` | |
| DELETE | `/api/speech/audio/:id` | Deletes the row and the file |
| GET | `/api/audio/:id` | Owner-only MP3 stream |
| POST | `/api/transcribe` | multipart `audio` → `{transcript}` (script from audio; not stored) |

---

## Security notes

- The API refuses to start without a `JWT_SECRET` of at least 32 characters. There are no default secrets.
- Engine API keys exist only in server environments and are never sent to the browser.
- Every query is scoped by `user_id`. Other users get 404s, and audio streaming requires the owner's JWT.
- CORS is limited to `ALLOWED_ORIGINS`. In Docker, all ports bind to `127.0.0.1`.
- Audit log entries cover register, login, failed logins, consent issue/verify/fail, uploads, queueing and deletes.

**Not done yet:** speaker verification (checking that the consent voice is the same person as the sample voice),
rate limiting, token revocation on logout, and S3 storage on the Rust side (the worker supports it).

## Repository layout

```
backend-rust/      Axum API (src/routes/*, consent_check.rs, migrations/)
worker-python/     Redis worker: jobs.py, engines/{f5,minimax,elevenlabs}.py, audio_utils.py
speech_pipeline/   Whisper + Silero VAD service (POST /api/v1/transcribe for consent checks)
frontend/          Dashboard (dashboard.html/.css/.js, config.js)
index.html …       Landing page
demo/              Legacy single-file Node demo (local only; see demo/README.md)
docker-compose.yml Full stack
```

## Local demo (legacy)

`demo/server.js` is the original in-memory Node prototype, kept only as a local demo. It has fake login and no
server-side consent enforcement. See [demo/README.md](demo/README.md).

## License

MIT. See [LICENSE](LICENSE).

This software is for lawful, consent-based cloning of your own voice only. Do not use it to impersonate anyone.
