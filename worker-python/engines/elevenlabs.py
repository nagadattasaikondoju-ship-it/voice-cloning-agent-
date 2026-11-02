"""ElevenLabs Instant Voice Cloning + TTS. Needs ELEVENLABS_API_KEY (IVC requires a paid plan)."""
import logging
import os
from typing import Any, Dict, Optional

import requests

from settings import ELEVENLABS_API_KEY, ELEVENLABS_BASE_URL, ELEVENLABS_MODEL

logger = logging.getLogger(__name__)


def _headers() -> Dict[str, str]:
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ElevenLabs engine is not configured (ELEVENLABS_API_KEY missing).")
    return {"xi-api-key": ELEVENLABS_API_KEY}


def _raise_for(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
            msg = detail.get("message") if isinstance(detail, dict) else detail
        except Exception:
            msg = resp.text[:300]
        raise RuntimeError(f"ElevenLabs error {resp.status_code}: {msg}")


def clone(sample_path: str, voice_id: str, display_name: str) -> Dict[str, Optional[str]]:
    with open(sample_path, "rb") as f:
        resp = requests.post(
            f"{ELEVENLABS_BASE_URL}/voices/add",
            headers=_headers(),
            data={
                "name": f"{display_name} ({voice_id})",
                "description": "User-owned voice cloned with verified spoken consent.",
                "remove_background_noise": "true",
            },
            files={"files": (os.path.basename(sample_path), f)},
            timeout=180,
        )
    _raise_for(resp)
    provider_id = resp.json().get("voice_id")
    if not provider_id:
        raise RuntimeError("ElevenLabs did not return a voice_id")
    return {"provider_voice_id": provider_id}


def synthesize(job: Dict[str, Any], clone_row: Dict[str, Any]) -> bytes:
    provider_id = clone_row.get("provider_voice_id")
    if not provider_id:
        raise RuntimeError("Voice has no ElevenLabs voice id")
    resp = requests.post(
        f"{ELEVENLABS_BASE_URL}/text-to-speech/{provider_id}",
        params={"output_format": "mp3_44100_128"},
        headers={**_headers(), "Content-Type": "application/json", "Accept": "audio/mpeg"},
        json={
            "text": job["text"],
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                # ElevenLabs supports 0.7–1.2
                "speed": max(0.7, min(1.2, float(job.get("speed", 1.0)))),
            },
        },
        timeout=180,
    )
    _raise_for(resp)
    return resp.content


def delete(voice_id: str, provider_voice_id: Optional[str]) -> None:
    if not provider_voice_id:
        return
    resp = requests.delete(f"{ELEVENLABS_BASE_URL}/voices/{provider_voice_id}", headers=_headers(), timeout=60)
    if resp.status_code != 404:
        _raise_for(resp)
