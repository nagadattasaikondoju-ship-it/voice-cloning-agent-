import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _real_key(name: str) -> str:
    value = os.getenv(name, "").strip()
    return "" if value.startswith(("your_", "mock_")) else value


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/voiceclone")

# Engines
MINIMAX_API_KEY = _real_key("MINIMAX_API_KEY")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "speech-2.8-hd")

ELEVENLABS_API_KEY = _real_key("ELEVENLABS_API_KEY")
ELEVENLABS_BASE_URL = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")

F5_SPACE = os.getenv("F5_SPACE", "mrfakename/E2-F5-TTS")
HF_TOKEN = os.getenv("HF_TOKEN", "").strip() or None
F5_REFERENCE_SECONDS = float(os.getenv("F5_REFERENCE_SECONDS", "12"))

# Whisper service used to transcribe F5 reference clips
SPEECH_PIPELINE_URL = os.getenv("SPEECH_PIPELINE_URL", "http://localhost:8000").rstrip("/")

# Storage (shared with the Rust API)
STORAGE_TYPE = os.getenv("STORAGE_TYPE", "local")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "../backend-rust/private_storage")).resolve()
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_BUCKET = os.getenv("S3_BUCKET", "voiceclone-private")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
