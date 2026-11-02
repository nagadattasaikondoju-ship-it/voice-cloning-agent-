"""ElevenLabs Instant Voice Cloning + TTS. Needs ELEVENLABS_API_KEY (IVC requires a paid plan)."""
import logging
import os
from typing import Any, Dict, Optional

import requests

from engines.errors import PermanentError

from settings import ELEVENLABS_API_KEY, ELEVENLABS_BASE_URL, ELEVENLABS_MODEL

logger = logging.getLogger(__name__)


def _headers() -> Dict[str, str]:
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ElevenLabs engine is not configured (ELEVENLABS_API_KEY missing).")
    return {"xi-api-key": ELEVENLABS_API_KEY}


ELEVENLABS_HINTS = {
    "missing_permissions": "API key lacks permissions (needs Voices write, Text to Speech, User read).",
    "can_not_use_instant_voice_cloning": "Your ElevenLabs plan does not include Instant Voice Cloning. Upgrade to Starter or above.",
    "voice_limit_reached": "ElevenLabs custom-voice limit reached for your plan. Delete old voices or upgrade.",
    "quota_exceeded": "ElevenLabs credits are used up for this billing period.",
    "invalid_api_key": "ElevenLabs rejected the API key.",
    "detected_unusual_activity": "ElevenLabs blocked free-tier use from this network. A paid plan is required.",
}


def _raise_for(resp: requests.Response) -> None:
    if resp.status_code < 400:
        return
    status, msg = "", resp.text[:300]
    try:
        detail = resp.json().get("detail")
        if isinstance(detail, dict):
            status, msg = detail.get("status", ""), detail.get("message", msg)
        elif detail:
            msg = str(detail)
    except Exception:
        pass
    hint = ELEVENLABS_HINTS.get(status) or next((h for k, h in ELEVENLABS_HINTS.items() if k in msg), msg)
    err = RuntimeError if resp.status_code in (429, 500, 502, 503, 504) else PermanentError
    raise err(f"ElevenLabs {resp.status_code}: {hint}")


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
