import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/voiceclone")

# Private storage shared with the Rust API (same directory / Docker volume).
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "../backend-rust/private_storage")).resolve()

# Sarvam AI voice cloning (hosted). Get a key at https://dashboard.sarvam.ai
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
SARVAM_API_URL = os.getenv("SARVAM_API_URL", "https://api.sarvam.ai/voices/clone").strip()
# Empty = detect from the text. Or one of: en-IN hi-IN bn-IN ta-IN te-IN kn-IN ml-IN mr-IN gu-IN pa-IN od-IN as-IN
SARVAM_LANGUAGE = os.getenv("SARVAM_LANGUAGE", "").strip()
# Ask Sarvam to isolate the speaker in the reference clip (adds ~1 s per request).
SARVAM_REMOVE_NOISE = os.getenv("SARVAM_REMOVE_NOISE", "false").strip().lower() in ("1", "true", "yes")
SARVAM_TIMEOUT = float(os.getenv("SARVAM_TIMEOUT", "120"))
