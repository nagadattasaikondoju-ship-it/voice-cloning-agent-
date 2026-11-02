"""
Chatterbox voice cloning engine (Resemble AI, MIT license). Runs locally on GPU or CPU.

One model instance per worker process. For each job the voice is conditioned once from
the reference clip, the text is split into sentence-sized chunks, and the chunks are
joined with a short pause. A fixed seed makes output repeatable for the same input.
"""
import logging
import re
import threading
from pathlib import Path
from typing import List, Optional

from settings import CHATTERBOX_DEVICE, CHATTERBOX_MODEL, CHATTERBOX_SEED

logger = logging.getLogger(__name__)

MODELS = {
    "turbo": "English (fast, 350M)",
    "multilingual": "23 languages (500M)",
}
MULTILINGUAL_LANGUAGES = [
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja",
    "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
]
MAX_CHUNK_CHARS = 250
PAUSE_SECONDS = 0.25

_lock = threading.Lock()
_model = None
_device = None


def languages() -> List[str]:
    return MULTILINGUAL_LANGUAGES if CHATTERBOX_MODEL == "multilingual" else ["en"]


def device() -> Optional[str]:
    return _device


def _pick_device() -> str:
    import torch

    if CHATTERBOX_DEVICE in ("cpu", "cuda"):
        return CHATTERBOX_DEVICE
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load(on: str):
    if CHATTERBOX_MODEL == "multilingual":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        return ChatterboxMultilingualTTS.from_pretrained(device=on)
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    return ChatterboxTurboTTS.from_pretrained(device=on)


def load() -> None:
    """Load (and on first run download) the model. Falls back to CPU if the GPU runs out of memory."""
    global _model, _device
    if CHATTERBOX_MODEL not in MODELS:
        raise ValueError(f"CHATTERBOX_MODEL must be one of {list(MODELS)}, got {CHATTERBOX_MODEL!r}")
    with _lock:
        if _model is not None:
            return
        target = _pick_device()
        logger.info(f"Loading Chatterbox '{CHATTERBOX_MODEL}' on {target} (first run downloads ~1-2 GB)...")
        try:
            _model, _device = _load(target), target
        except Exception as e:
            if target != "cuda" or "out of memory" not in str(e).lower():
                raise
            logger.warning("GPU out of memory while loading; falling back to CPU (slower).")
            import torch

            torch.cuda.empty_cache()
            _model, _device = _load("cpu"), "cpu"
        logger.info(f"Chatterbox ready on {_device}.")


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> List[str]:
    """Sentence-aware chunks of at most `limit` chars (long sentences split on commas, then words)."""
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    pieces: List[str] = []
    for s in sentences:
        while len(s) > limit:
            cut = max(s.rfind(", ", 0, limit), s.rfind(" ", 0, limit))
            cut = cut if cut > limit // 3 else limit
            pieces.append(s[:cut].strip(" ,"))
            s = s[cut:].strip(" ,")
        if s:
            pieces.append(s)
    chunks: List[str] = []
    for p in pieces:
        if chunks and len(chunks[-1]) + 1 + len(p) <= limit:
            chunks[-1] += " " + p
        else:
            chunks.append(p)
    return chunks


def synthesize(reference_wav: Path, text: str, language: str, out_wav: Path) -> None:
    """Speak `text` in the voice of `reference_wav`; writes a mono WAV at the model's sample rate."""
    import torch
    import torchaudio

    load()
    if language not in languages():
        raise ValueError(f"Language '{language}' is not supported by the '{CHATTERBOX_MODEL}' model.")
    chunks = split_text(text)
    if not chunks:
        raise ValueError("Text is empty.")

    with _lock:  # one generation at a time per model instance
        torch.manual_seed(CHATTERBOX_SEED)
        _model.prepare_conditionals(str(reference_wav))
        pause = torch.zeros(1, int(_model.sr * PAUSE_SECONDS))
        parts = []
        for i, chunk in enumerate(chunks):
            if CHATTERBOX_MODEL == "multilingual":
                wav = _model.generate(chunk, language_id=language)
            else:
                wav = _model.generate(chunk)
            parts.append(wav.cpu())
            if i < len(chunks) - 1:
                parts.append(pause)
        torchaudio.save(str(out_wav), torch.cat(parts, dim=1), _model.sr)
