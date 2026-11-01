Intelligence Designed To Evolve
A production-ready AI voice cloning and text-to-speech web application with a cinematic single-viewport landing page. The project uses a static HTML/CSS/vanilla JS frontend, a secure Rust backend, Python background workers, and the MiniMax API for voice cloning and speech generation.

The platform lets verified users clone their own voice, generate speech from text, preview and download MP3 audio, and manage or delete their cloned voices and generated files.

Features
Full-bleed looping video landing page

Retro dot-matrix headline and animated metrics

Responsive desktop and mobile navigation

User registration and JWT-based authentication

Voice sample recording and upload

Spoken consent verification

Voice cloning through MiniMax

Text-to-speech generation using cloned voices

MP3 preview and download

Private audio storage

Background job processing with Redis and RQ

Voice and generated-audio deletion

Audit logging and security controls

Tech Stack
Layer	Technology
Landing page	HTML, CSS, vanilla JavaScript
Dashboard	HTML, CSS, vanilla JavaScript
Backend API	Rust, Axum, SQLx, PostgreSQL
Background workers	Python, RQ, Redis
Voice AI	MiniMax Voice Clone and Text-to-Speech API
Database	PostgreSQL
Queue	Redis
File storage	S3-compatible object storage
Secrets	Antigravity-managed environment secrets
Architecture
text
Browser
  │
  ▼
Static Frontend
  │
  ▼
Rust API (Axum)
  │
  ├── PostgreSQL
  ├── Redis job queue
  └── S3-compatible storage
        │
        ▼
Python Worker
  │
  ├── MiniMax File Upload API
  ├── MiniMax Voice Clone API
  └── MiniMax Text-to-Speech API
        │
        ▼
Generated MP3 stored privately
Project Structure
text
.
├── index.html
├── styles.css
├── main.js
├── assets/
│   └── logo.webp
├── fonts/
│   └── GeistPixel-Circle.woff2
├── backend-rust/
│   ├── Cargo.toml
│   ├── .env.example
│   └── src/
├── worker-python/
│   ├── requirements.txt
│   ├── .env.example
│   ├── main.py
│   ├── minimax_client.py
│   ├── jobs.py
│   └── storage.py
├── frontend/
│   ├── dashboard.html
│   ├── dashboard.css
│   └── dashboard.js
├── docker-compose.yml
└── README.md
Getting Started
Prerequisites
Install the following:

Rust 1.75+

Python 3.11+

PostgreSQL 15+

Redis 7+

Node.js 18+ or any static file server

Docker and Docker Compose, optional

Clone the repository
bash
git clone https://github.com/your-username/intelligence-designed-to-evolve.git
cd intelligence-designed-to-evolve
Environment Variables
Create .env files from the examples.

Rust backend
bash
cp backend-rust/.env.example backend-rust/.env
text
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/voiceclone
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=replace_with_a_long_random_secret
MINIMAX_API_KEY=your_minimax_api_key
MINIMAX_BASE_URL=https://api.minimax.io/v1
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=voiceclone-private
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
ALLOWED_ORIGINS=http://localhost:5500,http://127.0.0.1:5500
Python worker
bash
cp worker-python/.env.example worker-python/.env
text
REDIS_URL=redis://localhost:6379/0
MINIMAX_API_KEY=your_minimax_api_key
MINIMAX_BASE_URL=https://api.minimax.io/v1
S3_ENDPOINT=http://localhost:9000
S3_BUCKET=voiceclone-private
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
Important: Never commit .env, API keys, JWT secrets, or cloud credentials. Store production secrets in Antigravity or another secret manager.

Install Dependencies
Rust backend
bash
cd backend-rust
cargo build
Python worker
bash
cd worker-python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Database Setup
Create the database:

sql
CREATE DATABASE voiceclone;
Run migrations:

bash
cd backend-rust
sqlx migrate run
The migrations create tables for:

users

consents

voice_samples

voice_clones

speech_jobs

generated_audio

audit_logs

Run the Application
1. Start PostgreSQL and Redis
If using Docker:

bash
docker compose up -d postgres redis
2. Start the Rust API
bash
cd backend-rust
cargo run
The API runs at:

text
http://localhost:8080
3. Start the Python worker
bash
cd worker-python
source .venv/bin/activate
rq worker voice_clone --url redis://localhost:6379/0
4. Serve the frontend
From the project root:

bash
python -m http.server 5500
Open:

text
http://localhost:5500
Docker Compose
To run PostgreSQL, Redis, the Rust API, and the Python worker together:

bash
docker compose up --build
Do not place real secrets directly in docker-compose.yml. Use .env, Docker secrets, or Antigravity-managed environment variables.

MiniMax Integration
The application uses three MiniMax API operations:

1. Upload voice sample
text
POST https://api.minimax.io/v1/files/upload
Authorization: Bearer <MINIMAX_API_KEY>
Content-Type: multipart/form-data
Form fields:

text
purpose=voice_clone
file=<audio file>
Supported formats:

MP3

M4A

WAV

Recommended source audio:

Duration: 10 seconds to 5 minutes

Maximum file size: 20 MB

Clean recording with minimal background noise

2. Create cloned voice
text
POST https://api.minimax.io/v1/voice_clone
Authorization: Bearer <MINIMAX_API_KEY>
Content-Type: application/json
Example request:

json
{
  "file_id": 123456789,
  "voice_id": "unique_user_voice_id",
  "text": "This is an approved preview of the cloned voice.",
  "model": "speech-2.8-hd",
  "need_noise_reduction": true,
  "need_volume_normalization": true
}
The API returns a cloned voice identifier that the application stores securely.

3. Generate speech
text
POST https://api.minimax.io/v1/t2a_v2
Authorization: Bearer <MINIMAX_API_KEY>
Content-Type: application/json
Example request:

json
{
  "model": "speech-2.8-hd",
  "text": "Welcome to Intelligence Designed To Evolve.",
  "stream": false,
  "language_boost": "auto",
  "voice_setting": {
    "voice_id": "cloned_voice_id",
    "speed": 1.0,
    "vol": 1.0,
    "pitch": 0
  },
  "audio_setting": {
    "sample_rate": 32000,
    "bitrate": 128000,
    "format": "mp3",
    "channel": 1
  }
}
The worker decodes the returned audio data, saves it as MP3, uploads it to private storage, and updates the speech job status.

API Endpoints
Authentication
text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
Consent
text
POST /api/consents
POST /api/consents/:id/verify
GET  /api/consents
Voice samples
text
POST /api/voice-samples
GET  /api/voice-samples
Voice cloning
text
POST   /api/voice-clones
GET    /api/voice-clones
GET    /api/voice-clones/:id
DELETE /api/voice-clones/:id
Speech generation
text
POST /api/speech/generate
GET  /api/speech/jobs/:id
GET  /api/speech/history
DELETE /api/speech/audio/:id
Consent and Safety
Voice cloning can be misused, so this project enforces the following rules:

Users may clone only their own voice.

Users must complete a recorded spoken-consent flow.

Users must explicitly confirm ownership and authorization.

Consent recordings, timestamps, phrases, and consent versions are stored.

Source audio is stored privately.

Users can revoke consent and delete cloned voices.

Generated audio is labeled as AI-generated.

API keys are never exposed to the browser.

Cross-user access is prevented through ownership checks.

Uploads are validated for type, duration, and file size.

Sensitive endpoints are rate-limited.

Security Practices
MiniMax API keys are server-side only.

Passwords are hashed using a modern password-hashing algorithm.

Authentication uses signed JWT tokens.

SQL queries use parameterized bindings.

CORS is restricted to configured origins.

Uploaded files are stored in private object storage.

Errors returned to clients avoid exposing internal details.

Audit logs record important security and user actions.

Deployment Checklist
Before deploying:

Use HTTPS everywhere.

Set a strong, unique JWT_SECRET.

Store MINIMAX_API_KEY in Antigravity or another secret manager.

Use a managed PostgreSQL database with automated backups.

Use managed Redis or a secured Redis instance.

Configure private S3-compatible storage with lifecycle policies.

Restrict CORS to production domains.

Enable rate limiting and request logging.

Set up error monitoring and worker health checks.

Configure database migrations to run safely during deployment.

Add regular security dependency updates.

Test consent, cloning, generation, deletion, and access-control flows.

Roadmap
Multi-speaker workspaces

Team billing and usage quotas

Streaming text-to-speech

Voice quality scoring

Pronunciation dictionary

Multilingual speech generation

Admin moderation dashboard

Watermarking for generated audio

Public API with developer keys

License
This project is licensed under the MIT License.

Disclaimer
This application is intended for lawful, consent-based voice cloning only. Do not use it to impersonate people, create misleading audio, bypass authentication systems, or generate content without the voice owner’s explicit permission.
