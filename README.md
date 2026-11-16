# Intelligence Designed To Evolve

Consent-verified voice cloning and text-to-speech on Sarvam AI's APIs. No GPU needed. A user can only clone their
**own** voice: the server issues a random phrase, the user reads it aloud, and the API refuses to create a clone until
Sarvam's transcript of that recording matches the phrase. That same recording is the sample the voice is cloned
from, so the voice that is cloned is the voice that consented. Each consent creates one voice.

- **Voice engine:** [Sarvam AI voice cloning](https://docs.sarvam.ai/api-reference/voice-cloning/clone) (hosted, needs a `SARVAM_API_KEY`, billed per character). Zero-shot cloning from a 6–15 s reference clip. English (Indian) plus Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam, Marathi, Gujarati, Punjabi, Odia and Assamese; cross-lingual, so one voice can speak any of them.
- **Rust (Axum) API:** auth, consent, uploads, ownership checks, audit log
- **Python worker:** processes jobs from Redis and calls the Sarvam API
- **Speech-to-text:** [Sarvam AI](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe), called by the Rust API: verifies spoken consent, turns audio into script text (audio is cut into 25 s pieces with ffmpeg)
- **Static dashboard:** HTML/CSS/vanilla JS, two tabs: **Voices** (read the consent phrase aloud → name it) and **Speak** (pick a voice, type or load a script, generate, play, download, history)

---

## Architecture

```
 Browser  http://localhost:5500  (index.html + frontend/dashboard.html)
    │  JWT (Authorization: Bearer), multipart audio uploads
    ▼
 Rust API  :8080  ──────────────►  Sarvam AI  POST https://api.sarvam.ai/speech-to-text
    │                                consent check: transcript vs phrase, word match ≥ 75%
    │                                audio → script text (/api/transcribe)
    ├──► PostgreSQL   users, consents, voice_samples, voice_clones, speech_jobs, generated_audio, audit_logs
    ├──► Redis        job queues: voice_clone_jobs · speech_jobs · delete_voice_jobs (JSON)
    │                 engine_health (worker heartbeat, every 30 s)
    └──► private_storage/   consents/ references/ generated/   (shared with the worker)
                   │
                   ▼
 Python worker ──► Sarvam AI  POST https://api.sarvam.ai/voices/clone
    clone:  consent recording → mono 24 kHz WAV, silence trimmed, ≤ 15 s → references/<voice>.wav
    speech: text split into ≤ 900-char chunks → each sent with the reference clip → joined with short pauses
            → speed (pitch-preserving), loudness normalized, volume → MP3 → generated/<job>.mp3
```

Every clip goes through the same steps (same reference processing, same loudness target), so all clips have the
same format and level.

### Cloning flow

1. `POST /api/consents`: the server generates a phrase with three random code words.
2. The user records it; `POST /api/consents/:id/verify` transcribes it and verifies it on a match of 75% or more. Each phrase allows 5 attempts.
3. `POST /api/voice-clones` with the verified consent queues the clone. The consent recording is the voice sample, and
   its transcript is sent to Sarvam as `ref_text`. The consent is marked used, so it cannot create a second voice.
4. `POST /api/speech/generate` queues speech; the dashboard polls `/api/speech/jobs/:id` and plays the owner-only MP3.

### Model

Sarvam AI voice cloning (beta API). The reference clip is sent with every request (it is not stored at Sarvam).
`SARVAM_LANGUAGE` forces the text language; empty means Sarvam detects it. Controls: speed (0.5–2×, pitch preserved) and volume.

---

## Quick start (Docker)

```bash
cp .env.example .env
```

Set `JWT_SECRET` and `SARVAM_API_KEY` (from https://dashboard.sarvam.ai) in `.env`; both are required. Generate the secret with:

```bash
openssl rand -hex 32
```

Start the stack:

```bash
docker compose up --build
```

| URL | What |
|---|---|
| http://localhost:5500/frontend/dashboard.html | Voice Studio (create an account, then clone) |
| http://localhost:5500 | Landing page |
| http://localhost:8080/api/health | Health of DB, Redis, speech-to-text config and the voice worker |

Nothing large is downloaded: speech-to-text and voice cloning both run on Sarvam.

## Hosted dashboard (Vercel)

The web pages are also published at **https://voice-cloning-studio-beta.vercel.app**
(dashboard: `/frontend/dashboard.html`). Only the static files are on Vercel (`.vercelignore`); the API,
and voice worker still run on **your** machine through Docker. The hosted page calls `http://localhost:8080`,
so it works only in a browser on the computer running the stack.

- `ALLOWED_ORIGINS` in `.env` must include the Vercel URL (it does in `.env.example`).
- Chrome may ask to allow access to devices on your local network. Click **Allow**.
- Other people opening the link see the pages but cannot use them unless they run the stack themselves.

## Local development (without Docker)

Needs Rust 1.89+, Python 3.11, PostgreSQL 15+, Redis 7+ and `ffmpeg`.

```bash
createdb voiceclone
```

Rust API (port 8080). Migrations run automatically:

```bash
cd backend-rust && cp .env.example .env    # set JWT_SECRET and SARVAM_API_KEY
cargo run
```

Worker (set `SARVAM_API_KEY` in its `.env`):

```bash
cd worker-python && python3.11 -m venv .venv && . .venv/bin/activate
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

Check the voice engine configuration by hand (prints status and any problem):

```bash
cd worker-python && python health.py
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Status pill says "Engine offline" | `worker-python` is not running | `docker compose logs worker-python` |
| "Engine error: SARVAM_API_KEY is not set" | No key in `.env` | Add the key and restart the worker |
| "Sarvam rejected the API key" / "quota exceeded" | Invalid key or no credits | Check the key and credits at https://dashboard.sarvam.ai |
| Words in the wrong language or accent | Language auto-detection guessed wrong | Set `SARVAM_LANGUAGE` (e.g. `en-IN`, `hi-IN`) |
| "Only X s of speech was found" | The recording is mostly silence | Read the whole phrase clearly, close to the mic |
| Consent "speech recognition is not configured" | `SARVAM_API_KEY` missing for `backend-rust` | Set it in `.env` and restart |
| "This consent was already used" | Each consent creates one voice | Record a new phrase |
| "Cannot reach the API" | Page opened as `file://` or from another origin | Open http://localhost:5500 |
| Microphone does not work | Browsers allow the mic only on localhost or HTTPS | Use localhost, or HTTPS when deployed |

## Scripts from files or audio

In the **Speak** tab, **Load script or audio** fills the script box from `.txt`, `.md`, `.srt` or `.vtt`.
Audio (mp3, m4a, wav, webm, ogg) is transcribed with Sarvam (up to 15 min), so an existing recording can be re-spoken in a cloned voice.

---

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | DB, Redis, speech-to-text config and worker status |
| GET | `/api/engine` | `{status: loading/ready/error/offline, model, device, problem}` |
| POST | `/api/auth/register` · `/api/auth/login` | `{email, password}` → `{token, user}` (JWT, 24 h) |
| POST | `/api/auth/logout` · GET `/api/auth/me` | |
| POST | `/api/consents` | Issues a consent phrase |
| POST | `/api/consents/:id/verify` | multipart `audio` → `{verified, transcript, match_score, threshold, attempts_remaining}` |
| GET | `/api/consents` | |
| POST | `/api/voice-clones` | `{consent_id, display_name}`: clones the verified consent recording (one voice per consent) |
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
- Reference clips and text are sent to Sarvam AI to generate speech. Do not use it for audio you may not share with them.

**Not done yet:** per-user usage limits (every generation spends Sarvam credits), rate limiting on login,
and token revocation on logout.

## Repository layout

```
backend-rust/      Axum API (src/routes/*, consent_check.rs, stt.rs, migrations/)
worker-python/     main.py (queue loop + heartbeat), tts.py (Sarvam API client), jobs.py, audio_utils.py, health.py
frontend/          Dashboard (dashboard.html/.css/.js, config.js)
index.html, styles.css   Landing page
docker-compose.yml          Full stack
```

## License

MIT. See [LICENSE](LICENSE). Use of the Sarvam API is subject to Sarvam AI's terms.

This software is for lawful, consent-based cloning of your own voice only. Do not use it to impersonate anyone.
