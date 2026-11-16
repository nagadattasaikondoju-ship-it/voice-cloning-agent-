"""
Sarvam AI voice cloning engine (hosted API, https://docs.sarvam.ai/api-reference/voice-cloning/clone).

Each request sends the prepared reference clip (`ref_audio`, at most 15 s) and up to 1000
characters of text, and gets back base64 audio in that voice. Longer text is split into
sentence-sized chunks, synthesized one by one, and joined with a short pause.

Languages: English (Indian) plus 11 Indian languages. Set SARVAM_LANGUAGE to force one,
or leave it empty to let Sarvam detect the language from the text.
"""
import base64
import io
import logging
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import List, Optional

import requests

from settings import (
    SARVAM_API_KEY,
    SARVAM_API_URL,
    SARVAM_LANGUAGE,
    SARVAM_REMOVE_NOISE,
    SARVAM_TIMEOUT,
)

logger = logging.getLogger(__name__)

MODEL = "sarvam-voice-clone"
MODEL_LABEL = "Sarvam AI voice cloning"
MAX_CHUNK_CHARS = 900  # API limit is 1000 characters per request
REFERENCE_MAX_SECONDS = 15.0  # API limit for ref_audio
SAMPLE_RATE = 24000
PAUSE_SECONDS = 0.25
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4

LANGUAGES = {"as-IN", "bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}


class SarvamError(RuntimeError):
    pass


def device() -> Optional[str]:
    return "cloud"


def load() -> None:
    """Nothing to download; just check the configuration so the dashboard shows a clear problem."""
    if not SARVAM_API_KEY:
        raise SarvamError("SARVAM_API_KEY is not set. Add your key from https://dashboard.sarvam.ai to .env.")
    if SARVAM_LANGUAGE and SARVAM_LANGUAGE not in LANGUAGES:
        raise SarvamError(f"SARVAM_LANGUAGE={SARVAM_LANGUAGE!r} is not supported. Use one of {sorted(LANGUAGES)} or leave it empty.")
    logger.info(f"Sarvam voice cloning ready ({SARVAM_API_URL}, language: {SARVAM_LANGUAGE or 'auto'}).")


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> List[str]:
    """Sentence-aware chunks of at most `limit` chars (long sentences split on commas, then words)."""
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?।॥。！？])\s+", text)
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


def _reference_bytes(reference_wav: Path) -> bytes:
    """The reference as WAV bytes, cut to the API's 15 s limit (older references may be up to 20 s)."""
    with wave.open(str(reference_wav), "rb") as w:
        seconds = w.getnframes() / float(w.getframerate())
    if seconds <= REFERENCE_MAX_SECONDS:
        return reference_wav.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        cut = Path(tmp) / "ref.wav"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(reference_wav), "-t", str(REFERENCE_MAX_SECONDS - 0.5), str(cut)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SarvamError(f"Could not trim the reference clip: {proc.stderr.strip()[-300:]}")
        return cut.read_bytes()


def _error_message(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error", {})
        msg, rid = err.get("message"), err.get("request_id")
    except Exception:  # noqa: BLE001
        msg, rid = resp.text[:300], None
    friendly = {
        402: "Sarvam quota exceeded. Top up credits at https://dashboard.sarvam.ai.",
        403: "Sarvam rejected the API key. Check SARVAM_API_KEY.",
    }.get(resp.status_code)
    text = friendly or f"Sarvam API error {resp.status_code}: {msg or 'unknown error'}"
    return f"{text} (request {rid})" if rid else text


def _reference_text(reference_wav: Path) -> Optional[str]:
    """Transcript saved next to the reference (references/<voice>.txt), if any."""
    path = reference_wav.with_suffix(".txt")
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text if 0 < len(text) <= 500 else None


def _clone_chunk(ref_audio: bytes, text: str, ref_text: Optional[str] = None) -> bytes:
    """One API call; returns WAV bytes. Retries rate limits and transient server errors."""
    data = {
        "text": text,
        "output_audio_codec": "wav",
        "speech_sample_rate": str(SAMPLE_RATE),
    }
    if SARVAM_LANGUAGE:
        data["language_code"] = SARVAM_LANGUAGE
    if ref_text:
        data["ref_text"] = ref_text
    if SARVAM_REMOVE_NOISE:
        data["remove_background_noise"] = "true"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(
                SARVAM_API_URL,
                headers={"api-subscription-key": SARVAM_API_KEY},
                data=data,
                files={"ref_audio": ("reference.wav", ref_audio, "audio/wav")},
                timeout=SARVAM_TIMEOUT,
            )
        except requests.RequestException as e:
            if attempt == MAX_ATTEMPTS:
                raise SarvamError(f"Could not reach Sarvam: {e}") from e
            time.sleep(2 ** attempt)
            continue
        if resp.ok:
            body = resp.json()
            b64 = body.get("audio_b64") or body.get("audio")
            if not b64:
                raise SarvamError(f"Sarvam returned no audio (request {body.get('request_id')}).")
            return base64.b64decode(b64)
        if resp.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
            logger.warning(f"Sarvam {resp.status_code}; retrying ({attempt}/{MAX_ATTEMPTS})")
            time.sleep(2 ** attempt)
            continue
        raise SarvamError(_error_message(resp))
    raise SarvamError("Sarvam request failed.")


def synthesize(reference_wav: Path, text: str, out_wav: Path) -> None:
    """Speak `text` in the voice of `reference_wav`; writes a mono 16-bit WAV at 24 kHz."""
    if not SARVAM_API_KEY:
        raise SarvamError("SARVAM_API_KEY is not set.")
    chunks = split_text(text)
    if not chunks:
        raise ValueError("Text is empty.")

    ref = _reference_bytes(reference_wav)
    ref_text = _reference_text(reference_wav)
    frames: List[bytes] = []
    params = None
    for i, chunk in enumerate(chunks):
        with wave.open(io.BytesIO(_clone_chunk(ref, chunk, ref_text)), "rb") as w:
            if params is None:
                params = w.getparams()
            elif (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (
                params.nchannels, params.sampwidth, params.framerate
            ):
                raise SarvamError("Sarvam returned audio chunks in different formats.")
            frames.append(w.readframes(w.getnframes()))
        if i < len(chunks) - 1:
            frames.append(b"\x00" * int(params.framerate * PAUSE_SECONDS) * params.sampwidth * params.nchannels)

    with wave.open(str(out_wav), "wb") as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(params.framerate)
        out.writeframes(b"".join(frames))
