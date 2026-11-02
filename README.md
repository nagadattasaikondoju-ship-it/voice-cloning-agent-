# Intelligence Designed To Evolve

A production-grade AI voice cloning and text-to-speech platform built with a high-performance **Rust (Axum)** API, **Python (RQ/Redis)** background worker, and a cinematic single-viewport **HTML/CSS/vanilla JS** landing page and authenticated voice studio.

Powered by the **MiniMax international API** (`https://api.minimax.io/v1`) using the state-of-the-art `speech-2.8-hd` model.

---

## 🏛 Architecture

```
                    Browser (Static Landing & Dashboard)
                                    │
                               HTTPS│ (JWT Auth, Audio Upload, Studio UI)
                                    ▼
                             Rust API (Axum)
                                    │
             ┌──────────────────────┼──────────────────────┐
             ▼                      ▼                      ▼
        PostgreSQL                Redis               Private Storage
    (Users, Consents,        (Job Queues:           (Local Encrypted /
     Clones, Audits)         voice_clone,             S3-compatible)
                             speech_jobs)                  │
                                    │                      │
                                    ▼                      │
                              Python Worker ◄──────────────┘
                                    │ (Upload sample, clone voice,
                                    │  decode hex audio to MP3)
                                    ▼
                         MiniMax Voice AI Engine
                       (https://api.minimax.io/v1)
```

---

## ✨ Features

- **Cinematic Single-Viewport Landing Page:** Full-bleed looping video background, retro dot-matrix typography, animated enterprise metric counters, and responsive drawer navigation.
- **Microphone & File Audio Onboarding:** Browser-based recording via `MediaRecorder` with real-time waveform level visualizer, plus drag-and-drop support for MP3, M4A, and WAV files (10s to 5min, up to 20MB).
- **Enforced Spoken Consent Verification:** Randomized legal challenge phrases, spoken verification recording, explicit owner authorization, and tamper-resistant audit logs.
- **Rapid Voice Cloning via MiniMax:** Automated audio upload to `/v1/files/upload` with `purpose=voice_clone` and instant voice registration at `/v1/voice_clone`.
- **Speech Synthesis Studio:** Text-to-speech with character counter, speed (0.5x–2.0x), volume (0.1–2.0), and pitch (-12 to +12) fine-tuning sliders.
- **Synchronous Hex-to-MP3 Decoding:** Real-time decoding of MiniMax hex audio streams into high-bitrate MP3 files with in-browser playback and direct download.
- **Complete Privacy & Voice Management:** One-click revocation and deletion of cloned voices from both MiniMax Voice Management and database, plus MP3 purge tools.

---

## 📁 Project Structure

```
.
├── index.html                     # Single-viewport landing page
├── styles.css                     # Responsive styles, typography & animations
├── main.js                        # Count-up observer & mobile drawer
├── assets/
│   └── logo.webp                  # Scaled circular brand emblem
├── fonts/
│   └── GeistPixel-Circle.woff2    # Local fallback display font
├── frontend/
│   ├── dashboard.html             # Authenticated Voice Studio & TTS UI
│   ├── dashboard.css              # Dark theme styling, players & visualizers
│   └── dashboard.js               # Voice onboarding, consent & TTS studio logic
├── backend-rust/
│   ├── Cargo.toml                 # Axum, Tokio, SQLx, Redis, JWT dependencies
│   ├── Dockerfile                 # Multi-stage production container
│   ├── .env.example               # Environment variables template
│   ├── migrations/
│   │   └── 20261101000000_init_schema.sql # PostgreSQL database schema
│   └── src/
│       ├── main.rs                # HTTP server, routing & CORS
│       ├── config.rs              # Environment variable loader
│       ├── db.rs                  # Connection pools & audit logger
│       ├── auth.rs                # JWT generator/validator & AuthUser extractor
│       ├── models.rs              # Database records & DTO structs
│       └── routes/
│           ├── mod.rs
│           ├── auth_routes.rs     # Register, Login, Logout, Me
│           ├── consent_routes.rs  # Consent creation, verification, lookup
│           ├── clone_routes.rs    # Voice sample upload & clone jobs
│           └── speech_routes.rs   # TTS generation, history & audio streaming
├── worker-python/
│   ├── requirements.txt           # Python dependencies (requests, redis, rq, boto3)
│   ├── Dockerfile                 # Containerized worker definition
│   ├── .env.example               # Worker environment template
│   ├── main.py                    # Redis queue listener loop
│   ├── settings.py                # Worker config loader
│   ├── minimax_client.py          # MiniMax API upload, clone, TTS & delete client
│   ├── jobs.py                    # Worker job implementations with retries
│   └── storage.py                 # Private file & S3 storage adapter
├── docker-compose.yml             # Orchestration for PostgreSQL, Redis, API & Worker
└── README.md
```

---

## 🚀 Quick Start with Docker Compose

Run all services (PostgreSQL, Redis, Rust backend, and Python worker) in one command:

```bash
docker compose up --build
```

Then serve the landing page or open it in your browser:

```bash
python -m http.server 5500
```
- **Landing Page:** [http://localhost:5500](http://localhost:5500)
- **Voice Studio Dashboard:** [http://localhost:5500/frontend/dashboard.html](http://localhost:5500/frontend/dashboard.html)
- **Rust Backend API:** [http://localhost:8080](http://localhost:8080)

---

## 🛠 Local Development Setup

### 1. Prerequisites
- **Rust 1.75+** & Cargo
- **Python 3.11+** & Virtualenv
- **PostgreSQL 15+**
- **Redis 7+**

### 2. Environment Configuration

Copy the sample environment files:

```bash
# Rust backend
cp backend-rust/.env.example backend-rust/.env

# Python worker
cp worker-python/.env.example worker-python/.env
```

Set your **MiniMax API Key** in both `.env` files:
```ini
MINIMAX_API_KEY=your_minimax_api_key_here
```

### 3. Database Migration

Create and migrate the PostgreSQL database:

```sql
CREATE DATABASE voiceclone;
```

Run SQLx migrations:
```bash
cd backend-rust
cargo install sqlx-cli --no-default-features --features postgres
sqlx migrate run
```

### 4. Run Rust Backend

```bash
cd backend-rust
cargo run
```
The API starts on `http://0.0.0.0:8080`.

### 5. Run Python Worker

```bash
cd worker-python
python -m venv .venv
source .venv/bin/activate # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 6. Preview Frontend

From the root directory:
```bash
python -m http.server 5500
```
Open `http://localhost:5500` in any web browser.

---

## 🔐 Security & Consent Rules

1. **Owner-Only Voice Cloning:** The system strictly rejects cloning attempts if the spoken consent has not been recorded and verified by the authenticated user.
2. **Server-Side API Key Isolation:** `MINIMAX_API_KEY` is never transmitted to the browser or included in frontend bundles. It resides solely in server environments and Antigravity-managed secrets.
3. **Private Encrypted Storage:** Raw audio recordings and generated synthetic speech files are stored in private object storage, never exposed publicly.
4. **Voice Revocation:** Cloned voice models can be permanently purged via the dashboard, which issues a delete command to MiniMax's Voice Management API.
5. **AI Disclosure:** Every audio clip generated includes transparent metadata disclosure indicating synthetic voice generation.

---

## 📡 API Reference

### Authentication
- `POST /api/auth/register` — Create a new account with email & password.
- `POST /api/auth/login` — Sign in and receive a signed JWT token.
- `POST /api/auth/logout` — Invalidate session.
- `GET /api/auth/me` — Retrieve authenticated user profile.

### Consent & Compliance
- `POST /api/consents` — Record spoken consent phrase and audio metadata.
- `POST /api/consents/:id/verify` — Verify ownership consent.
- `GET /api/consents` — List active user consents.

### Voice Samples & Cloning
- `POST /api/voice-samples` — Upload MP3/M4A/WAV voice sample (multipart).
- `GET /api/voice-samples` — List uploaded voice samples.
- `POST /api/voice-clones` — Submit verified voice clone job to MiniMax worker.
- `GET /api/voice-clones` — List active cloned voices.
- `GET /api/voice-clones/:id` — Get clone job status.
- `DELETE /api/voice-clones/:id` — Delete clone from database and purge from MiniMax.

### Speech Synthesis
- `POST /api/speech/generate` — Generate speech using cloned voice model.
- `GET /api/speech/jobs/:id` — Poll synthesis job status and retrieve audio URL.
- `GET /api/speech/history` — List past speech generation history.
- `DELETE /api/speech/audio/:id` — Delete generated audio recording.
- `GET /api/audio/:id` — Stream private MP3 audio securely.

---

## 📄 License
MIT License. See [LICENSE](LICENSE) for details.
