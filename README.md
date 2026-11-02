# Intelligence Designed To Evolve

Consent-verified voice cloning and text-to-speech that runs entirely on your own machine: free, no API keys,
no usage limits. A user can only clone their **own** voice. The server issues a random phrase, the user reads it
aloud, and the API refuses to create a clone until Whisper's transcript of that recording matches the phrase.

- **Voice engine:** [Chatterbox Turbo](https://github.com/resemble-ai/chatterbox) by Resemble AI (MIT license, commercial use allowed). English. Zero-shot cloning from 6–30 s of speech. Every clip carries an inaudible AI watermark.
- **Rust (Axum) API:** auth, consent, uploads, ownership checks, audit log
- **Python worker:** runs the Chatterbox model on GPU or CPU and processes jobs from Redis
- **Whisper speech pipeline** (faster-whisper): verifies spoken consent, turns audio into script text
- **Static dashboard:** HTML/CSS/vanilla JS, two tabs: **Voices** (record or upload a sample → read the consent phrase → name it) and **Speak** (pick a voice, type or load a script, generate, play, download, history)

---

## Architecture

```
 Browser  http://localhost:5500  (index.html + frontend/dashboard.html)
    │  JWT (Authorization: Bearer), multipart audio uploads
    ▼
 Rust API  :8080  ──────────────►  speech_pipeline :8000  (Whisper, CPU)
    │                                consent check: transcript vs phrase, word match ≥ 75%
    │                                audio → script text (/api/transcribe)
    ├──► PostgreSQL   users, consents, voice_samples, voice_clones, speech_jobs, generated_audio, audit_logs
    ├──► Redis        job queues: voice_clone_jobs · speech_jobs · delete_voice_jobs (JSON)
    │                 engine_health (worker heartbeat, every 30 s)
    └──► private_storage/   samples/ consents/ references/ generated/   (shared with the worker)
                   │
                   ▼
 Python worker ──► Chatterbox (GPU if available, else CPU)
    clone:  sample → mono 24 kHz WAV, silence trimmed, ≤ 20 s → references/<voice>.wav
    speech: text split into sentences → generated in the cloned voice → joined with short pauses
            → speed (pitch-preserving), loudness normalized, volume → MP3 → generated/<job>.mp3
```

Every clip goes through the same steps (fixed seed, same reference processing, same loudness target), so the same
text and voice always produce the same audio, and all clips have the same format and level.

### Cloning flow

1. `POST /api/consents`: the server generates a phrase with three random code words.
2. The user records it; `POST /api/consents/:id/verify` transcribes it and verifies it on a match of 75% or more. Each phrase allows 5 attempts.
3. `POST /api/voice-samples` stores 6 s–5 min of speech. `POST /api/voice-clones` (requires your verified consent) queues the clone.
4. `POST /api/speech/generate` queues speech; the dashboard polls `/api/speech/jobs/:id` and plays the owner-only MP3.

### Model

Chatterbox Turbo: English, 350M parameters, fits a 4 GB GPU, and falls back to CPU if the GPU runs out of memory.
Controls: speed (0.5–2×, pitch preserved) and volume.

---

## Quick start (Docker)

```bash
cp .env.example .env
```

Set `JWT_SECRET` in `.env` (required). Generate one with:

```bash
openssl rand -hex 32
```

With an NVIDIA GPU (Windows: Docker Desktop with WSL2 and a current NVIDIA driver):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

Without a GPU (set `TORCH_VARIANT=cpu` in `.env` for a smaller image):

```bash
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:5500/frontend/dashboard.html | Voice Studio (create an account, then clone) |
| http://localhost:5500 | Landing page |
| http://localhost:8080/api/health | Health of DB, Redis, Whisper and the voice worker |

The first start downloads the voice model (about 1–2 GB) and Whisper. The dashboard shows "Loading model…" until
the worker is ready. Plan for about 20–25 GB of free disk for images and models.

To check that Docker can see your GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

## Hosted dashboard (Vercel)

The web pages are also published at **https://voice-cloning-studio-beta.vercel.app**
(dashboard: `/frontend/dashboard.html`). Only the static files are on Vercel (`.vercelignore`); the API,
voice worker and Whisper still run on **your** machine through Docker. The hosted page calls `http://localhost:8080`,
so it works only in a browser on the computer running the stack.

- `ALLOWED_ORIGINS` in `.env` must include the Vercel URL (it does in `.env.example`).
- Chrome may ask to allow access to devices on your local network. Click **Allow**.
- Other people opening the link see the pages but cannot use them unless they run the stack themselves.

## Local development (without Docker)

Needs Rust 1.89+, Python 3.11 (Chatterbox needs 3.10–3.12), PostgreSQL 15+, Redis 7+ and `ffmpeg`.

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

Rust API (port 8080). Migrations run automatically:

```bash
cd backend-rust && cp .env.example .env    # set JWT_SECRET
cargo run
```

Worker. Use `cu124` instead of `cpu` for an NVIDIA GPU:

```bash
cd worker-python && python3.11 -m venv .venv && . .venv/bin/activate
pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt && cp .env.example .env
python main.py
```

Static frontend, from the repo root:

```bash
python -m http.server 5500
```

### Tests

```bash
cd backend-rust && cargo test
```

```bash
cd speech_pipeline && pytest
```

Check the voice engine by hand (loads the model, prints device and status):

```bash
cd worker-python && python health.py
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Status pill says "Engine offline" | `worker-python` is not running | `docker compose logs worker-python` |
| "Loading model…" for a long time | First start is downloading the model | Wait; check the worker log for download progress |
| Worker log: GPU out of memory, falling back to CPU | Another program is using GPU memory | Close GPU-heavy apps and restart the worker |
| Generation is slow | Running on CPU | Use the GPU compose file; check the dashboard shows "on GPU" |
| "Only X s of speech was found" | Sample is mostly silence or too short | Record 10–30 s of clear speech |
| Consent "speech recognition unavailable" | `speech-pipeline` is down or downloading Whisper | `docker compose logs speech-pipeline` |
| "Cannot reach the API" | Page opened as `file://` or from another origin | Open http://localhost:5500 |
| Microphone does not work | Browsers allow the mic only on localhost or HTTPS | Use localhost, or HTTPS when deployed |

## Scripts from files or audio

In the **Speak** tab, **Load script or audio** fills the script box from `.txt`, `.md`, `.srt` or `.vtt`.
Audio (mp3, m4a, wav, webm, ogg) is transcribed with Whisper, so an existing recording can be re-spoken in a cloned voice.

---

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | DB, Redis, Whisper and worker status |
| GET | `/api/engine` | `{status: loading/ready/error/offline, model, device, problem}` |
| POST | `/api/auth/register` · `/api/auth/login` | `{email, password}` → `{token, user}` (JWT, 24 h) |
| POST | `/api/auth/logout` · GET `/api/auth/me` | |
| POST | `/api/consents` | Issues a consent phrase |
| POST | `/api/consents/:id/verify` | multipart `audio` → `{verified, transcript, match_score, threshold, attempts_remaining}` |
| GET | `/api/consents` | |
| POST / GET | `/api/voice-samples` | multipart `audio` (mp3/m4a/wav/webm/ogg, ≤ 20 MB) + `duration` |
| POST | `/api/voice-clones` | `{consent_id, sample_id, display_name}` |
| GET | `/api/voice-clones` · `/api/voice-clones/:id` | |
| DELETE | `/api/voice-clones/:id` | Deletes the voice and its reference clip |
| POST | `/api/speech/generate` | `{voice_clone_id, text, speed?, volume?}` → job |
| GET | `/api/speech/jobs/:id` · `/api/speech/history` | |
| DELETE | `/api/speech/audio/:id` | Deletes the row and the file |
| GET | `/api/audio/:id` | Owner-only MP3 stream |
| POST | `/api/transcribe` | multipart `audio` → `{transcript}` (not stored) |

---

## Security notes

- The API refuses to start without a `JWT_SECRET` of at least 32 characters.
- Every query is scoped by `user_id`. Other users get 404s, and audio streaming requires the owner's JWT.
- CORS is limited to `ALLOWED_ORIGINS`; in Docker, all ports bind to `127.0.0.1`.
- Audit log entries cover register, login, failed logins, consent issue/verify/fail, uploads, queueing and deletes.
- Generated audio is watermarked by Chatterbox (Resemble PerTh).

**Not done yet:** speaker verification (checking that the consent voice is the same person as the sample voice),
rate limiting, and token revocation on logout.

## Repository layout

```
backend-rust/      Axum API (src/routes/*, consent_check.rs, stt.rs, migrations/)
worker-python/     main.py (queue loop + heartbeat), tts.py (Chatterbox), jobs.py, audio_utils.py, health.py
speech_pipeline/   Whisper service (POST /api/v1/transcribe)
frontend/          Dashboard (dashboard.html/.css/.js, config.js)
index.html, styles.css   Landing page
docker-compose.yml          Full stack (CPU)
docker-compose.gpu.yml      Adds the NVIDIA GPU to the voice worker
```

## License

MIT. See [LICENSE](LICENSE). Chatterbox is MIT-licensed by Resemble AI.

This software is for lawful, consent-based cloning of your own voice only. Do not use it to impersonate anyone.
