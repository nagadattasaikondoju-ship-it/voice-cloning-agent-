"""
F5-TTS zero-shot cloning via a public Hugging Face Space (free, no API key).

There is no persistent provider-side voice: "cloning" prepares a short reference clip
plus its Whisper transcript, and every synthesis sends both to the Space.
Set HF_TOKEN to raise ZeroGPU quotas. Pitch and volume are not supported by this engine.
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from audio_utils import convert
from settings import F5_REFERENCE_SECONDS, F5_SPACE, HF_TOKEN, SPEECH_PIPELINE_URL, STORAGE_DIR

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from gradio_client import Client

        logger.info(f"Connecting to F5-TTS Space '{F5_SPACE}'...")
        _client = Client(F5_SPACE, token=HF_TOKEN, verbose=False)
    return _client


def transcribe(path: str) -> str:
    with open(path, "rb") as f:
        resp = requests.post(
            f"{SPEECH_PIPELINE_URL}/api/v1/transcribe",
            files={"file": (os.path.basename(path), f, "audio/wav")},
            timeout=300,
        )
    resp.raise_for_status()
    return (resp.json().get("transcript") or "").strip()


def clone(sample_path: str, voice_id: str, display_name: str) -> Dict[str, Optional[str]]:
    # F5 conditions on ≤15 s of reference audio; trim first so the transcript matches the clip.
    ref_key = f"references/{voice_id}.wav"
    ref_path = str(STORAGE_DIR / ref_key)
    convert(sample_path, ref_path, max_seconds=F5_REFERENCE_SECONDS, mono_16k=False)
    reference_text = transcribe(ref_path)
    if len(reference_text.split()) < 3:
        raise RuntimeError("Could not hear enough speech in the sample to build a reference transcript.")
    return {"reference_audio_key": ref_key, "reference_text": reference_text}


def synthesize(job: Dict[str, Any], clone_row: Dict[str, Any]) -> bytes:
    from gradio_client import handle_file

    ref_key = clone_row.get("reference_audio_key")
    ref_text = clone_row.get("reference_text") or ""
    if not ref_key:
        raise RuntimeError("Voice has no F5 reference clip; re-create the voice.")
    result = _get_client().predict(
        handle_file(str(STORAGE_DIR / ref_key)),
        ref_text,
        job["text"],
        True,  # remove_silence
        api_name="/predict",
    )
    out_path = result if isinstance(result, str) else (result or {}).get("path")
    if not out_path or not Path(out_path).exists():
        raise RuntimeError("F5-TTS Space returned no audio")
    return Path(out_path).read_bytes()


def delete(voice_id: str, provider_voice_id: Optional[str]) -> None:
    (STORAGE_DIR / f"references/{voice_id}.wav").unlink(missing_ok=True)
