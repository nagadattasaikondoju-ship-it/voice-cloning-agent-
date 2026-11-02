import base64
import logging
from pathlib import Path
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger("speech_pipeline.recorder")


def decode_base64_audio(base64_str: str) -> Tuple[bytes, str]:
    """
    Decodes a base64 audio string, automatically stripping any data URL header
    such as 'data:audio/webm;codecs=opus;base64,'.
    Returns (audio_bytes, format_hint).
    """
    format_hint = "wav"
    if "," in base64_str and "base64" in base64_str:
        header, b64_data = base64_str.split(",", 1)
        if "webm" in header:
            format_hint = "webm"
        elif "ogg" in header:
            format_hint = "ogg"
        elif "mp3" in header:
            format_hint = "mp3"
        elif "wav" in header:
            format_hint = "wav"
        elif "m4a" in header:
            format_hint = "m4a"
    else:
        b64_data = base64_str

    audio_bytes = base64.b64decode(b64_data)
    return audio_bytes, format_hint


def save_audio_bytes(data: bytes, dest_path: Path) -> Path:
    """Saves raw audio bytes to destination path."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path


def capture_microphone(duration_s: float = 5.0, sample_rate: int = 16000) -> Optional[np.ndarray]:
    """
    Captures live audio from local microphone using sounddevice.
    Returns 1D numpy array of float32 samples or None if sounddevice is unavailable.
    """
    try:
        import sounddevice as sd
        logger.info(f"Recording {duration_s} seconds from microphone at {sample_rate}Hz...")
        recorded = sd.rec(
            int(duration_s * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32"
        )
        sd.wait()
        return recorded.flatten()
    except Exception as e:
        logger.warning(f"Microphone capture unavailable: {e}")
        return None
