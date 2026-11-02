import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/voiceclone")

# Private storage shared with the Rust API (same directory / Docker volume).
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "../backend-rust/private_storage")).resolve()

# Chatterbox (Resemble AI, MIT license), runs locally.
#   turbo         English, 350M params, fastest, fits 4 GB GPUs
#   multilingual  23 languages (incl. Hindi), 500M params, slower
CHATTERBOX_MODEL = os.getenv("CHATTERBOX_MODEL", "turbo").strip().lower()
# auto = CUDA if available, else CPU. Set "cpu" to force CPU.
CHATTERBOX_DEVICE = os.getenv("CHATTERBOX_DEVICE", "auto").strip().lower()
# Fixed seed so the same text + voice gives the same audio every time.
CHATTERBOX_SEED = int(os.getenv("CHATTERBOX_SEED", "42"))
