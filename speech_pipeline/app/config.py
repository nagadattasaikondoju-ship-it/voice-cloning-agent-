import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Storage Paths
    storage_dir: Path = Path("storage")
    sqlite_db_path: Path = Path("storage/pipeline.db")

    # ASR / Whisper Model
    whisper_device: str = "auto"
    whisper_model_gpu: str = "large-v3"
    whisper_model_cpu: str = "base"
    whisper_compute_type: str = "auto"
    whisper_language: Optional[str] = None
    whisper_word_timestamps: bool = True

    # Silero VAD Configuration
    vad_sample_rate: int = 16000
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 200
    vad_min_silence_duration_ms: int = 400
    vad_speech_pad_ms: int = 200
    vad_max_speech_duration_s: float = 5.0
    vad_overlap_ms: int = 200

    # Pipeline Processing
    parallel_workers: int = 1
    paragraph_silence_threshold_s: float = 1.5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def get_whisper_device_and_model(self) -> tuple[str, str, str]:
        """
        Resolves device (cuda/cpu), model name (large-v3 / base), and compute_type.
        GPU if available; falls back to CPU.
        """
        device = self.whisper_device.lower()
        if device == "auto":
            try:
                import torch
                is_cuda = torch.cuda.is_available()
            except ImportError:
                is_cuda = False
            device = "cuda" if is_cuda else "cpu"

        if device == "cuda":
            model = self.whisper_model_gpu
            compute = "float16" if self.whisper_compute_type == "auto" else self.whisper_compute_type
        else:
            model = self.whisper_model_cpu
            compute = "int8" if self.whisper_compute_type == "auto" else self.whisper_compute_type

        return device, model, compute


settings = Settings()

# Ensure base directories exist
settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
(settings.storage_dir / "recordings").mkdir(parents=True, exist_ok=True)
