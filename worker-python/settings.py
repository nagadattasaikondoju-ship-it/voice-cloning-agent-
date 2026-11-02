import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/voiceclone")

# Private storage shared with the Rust API (same directory / Docker volume).
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "../backend-rust/private_storage")).resolve()

# Chatterbox Turbo (Resemble AI, MIT license): English, 350M params, fits 4 GB GPUs. Runs locally.
# auto = CUDA if available, else CPU. Set "cpu" to force CPU.
CHATTERBOX_DEVICE = os.getenv("CHATTERBOX_DEVICE", "auto").strip().lower()
# Fixed seed so the same text + voice gives the same audio every time.
CHATTERBOX_SEED = int(os.getenv("CHATTERBOX_SEED", "42"))
