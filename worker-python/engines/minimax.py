"""MiniMax voice clone + T2A v2 (https://api.minimax.io/v1). Paid; needs MINIMAX_API_KEY."""
import logging
import os
import tempfile
from typing import Any, Dict, Optional

import requests

from engines.errors import PermanentError

from audio_utils import convert
from settings import MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL

logger = logging.getLogger(__name__)


def _headers(json_body: bool = False) -> Dict[str, str]:
    if not MINIMAX_API_KEY:
        raise RuntimeError("MiniMax engine is not configured (MINIMAX_API_KEY missing).")
    h = {"Authorization": f"Bearer {MINIMAX_API_KEY}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


MINIMAX_ERRORS = {
    1002: "MiniMax rate limit hit. Wait a minute and try again.",
    1004: "MiniMax rejected the API key. Check MINIMAX_API_KEY and that it matches MINIMAX_BASE_URL "
          "(international: api.minimax.io, mainland China: api.minimaxi.com).",
    1008: "MiniMax account balance is insufficient. Top up at platform.minimax.io (voice cloning and speech are paid).",
    1039: "MiniMax token-per-minute limit hit. Try again shortly.",
    1042: "Text contains too many unsupported characters.",
    1043: "MiniMax says the sample audio does not match its transcript.",
    2013: "MiniMax rejected the request parameters (sample must be 10 s–5 min mp3/m4a/wav, under 20 MB).",
    2038: "MiniMax account has no voice-cloning permission. Complete account verification at platform.minimax.io.",
}


def _check(payload: Dict[str, Any]) -> Dict[str, Any]:
    # MiniMax reports most errors with HTTP 200 and a non-zero base_resp.status_code.
    base = payload.get("base_resp") or {}
    code = base.get("status_code", 0)
    if code != 0:
        hint = MINIMAX_ERRORS.get(code, base.get("status_msg") or "unknown error")
        err = RuntimeError if code in (1000, 1001, 1002, 1013, 1039) else PermanentError
        raise err(f"MiniMax {code}: {hint}")
    return payload


def upload_voice_sample(file_path: str) -> int:
    """POST /files/upload (purpose=voice_clone). MiniMax accepts mp3/m4a/wav, 10 s–5 min, ≤20 MB."""
    with tempfile.TemporaryDirectory() as tmp:
        if not file_path.lower().endswith((".mp3", ".m4a", ".wav")):
            file_path = convert(file_path, os.path.join(tmp, "sample.mp3"))
        name = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{MINIMAX_BASE_URL}/files/upload",
                headers=_headers(),
                data={"purpose": "voice_clone"},
                files={"file": (name, f)},
                timeout=120,
            )
    resp.raise_for_status()
    payload = _check(resp.json())
    file_id = (payload.get("file") or {}).get("file_id") or payload.get("file_id")
    if not file_id:
        raise RuntimeError("MiniMax upload response did not contain a file_id")
    return int(file_id)


def clone(sample_path: str, voice_id: str, display_name: str) -> Dict[str, Optional[str]]:
    # Note: MiniMax deletes a cloned voice that is not used for speech within 7 days.
    file_id = upload_voice_sample(sample_path)
    resp = requests.post(
        f"{MINIMAX_BASE_URL}/voice_clone",
        headers=_headers(json_body=True),
        json={
            "file_id": file_id,
            "voice_id": voice_id,
            "model": MINIMAX_MODEL,
            "need_noise_reduction": True,
            "need_volume_normalization": True,
        },
        timeout=120,
    )
    resp.raise_for_status()
    _check(resp.json())
    return {"provider_voice_id": voice_id}


def synthesize(job: Dict[str, Any], clone_row: Dict[str, Any]) -> bytes:
    resp = requests.post(
        f"{MINIMAX_BASE_URL}/t2a_v2",
        headers=_headers(json_body=True),
        json={
            "model": MINIMAX_MODEL,
            "text": job["text"],
            "stream": False,
            "language_boost": "auto",
            "voice_setting": {
                "voice_id": clone_row.get("provider_voice_id") or job["voice_id"],
                "speed": float(job.get("speed", 1.0)),
                "vol": float(job.get("volume", 1.0)),
                "pitch": int(job.get("pitch", 0)),
            },
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        },
        timeout=180,
    )
    resp.raise_for_status()
    payload = _check(resp.json())
    audio_hex = (payload.get("data") or {}).get("audio")
    if not audio_hex:
        raise RuntimeError("MiniMax returned no audio")
    return bytes.fromhex(audio_hex)


def delete(voice_id: str, provider_voice_id: Optional[str]) -> None:
    resp = requests.post(
        f"{MINIMAX_BASE_URL}/delete_voice",
        headers=_headers(json_body=True),
        json={"voice_type": "voice_cloning", "voice_id": provider_voice_id or voice_id},
        timeout=60,
    )
    resp.raise_for_status()
    _check(resp.json())
