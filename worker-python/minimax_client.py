import os
import logging
import requests
from typing import Dict, Any

from settings import MINIMAX_API_KEY, MINIMAX_BASE_URL

logger = logging.getLogger(__name__)


def _get_headers() -> Dict[str, str]:
    if not MINIMAX_API_KEY:
        raise ValueError("MINIMAX_API_KEY is not configured in the environment.")
    return {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
    }


def upload_voice_sample(file_path: str) -> int:
    """
    Upload source audio to MiniMax via POST /v1/files/upload with purpose=voice_clone.
    Supported formats: MP3, M4A, WAV (10s to 5 mins, max 20MB).
    Returns the integer file_id.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Audio file not found at: {file_path}")

    url = f"{MINIMAX_BASE_URL}/files/upload"
    filename = os.path.basename(file_path)

    logger.info(f"Uploading voice sample '{filename}' to MiniMax...")

    with open(file_path, "rb") as audio_file:
        files = {
            "file": (filename, audio_file, "audio/mpeg" if filename.endswith(".mp3") else "audio/wav")
        }
        data = {
            "purpose": "voice_clone"
        }
        response = requests.post(
            url,
            headers=_get_headers(),
            data=data,
            files=files,
            timeout=120,
        )

    response.raise_for_status()
    payload = response.json()

    # MiniMax format: {"file": {"file_id": 123456789, ...}, "base_resp": {...}}
    file_id = payload.get("file", {}).get("file_id")
    if not file_id:
        # Fallback inspection for alternative response schemas
        file_id = payload.get("file_id")

    if not file_id:
        raise ValueError(f"MiniMax response did not contain file_id: {payload}")

    logger.info(f"Voice sample successfully uploaded. Received MiniMax file_id: {file_id}")
    return int(file_id)


def create_voice_clone(file_id: int, voice_id: str, preview_text: str = "This is an approved preview of the cloned voice.") -> Dict[str, Any]:
    """
    Call POST /v1/voice_clone with returned file_id and custom voice_id.
    Uses speech-2.8-hd model with noise reduction and volume normalization.
    """
    url = f"{MINIMAX_BASE_URL}/voice_clone"
    headers = _get_headers()
    headers["Content-Type"] = "application/json"

    payload = {
        "file_id": file_id,
        "voice_id": voice_id,
        "text": preview_text,
        "model": "speech-2.8-hd",
        "need_noise_reduction": True,
        "need_volume_normalization": True,
    }

    logger.info(f"Submitting voice clone request for voice_id '{voice_id}' using file_id {file_id}...")
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()
    result = response.json()
    logger.info(f"MiniMax voice_clone response received for '{voice_id}': {result.get('base_resp', {})}")
    return result


def generate_speech(
    voice_id: str,
    text: str,
    speed: float = 1.0,
    volume: float = 1.0,
    pitch: int = 0
) -> Dict[str, Any]:
    """
    Generate synthetic speech using POST /v1/t2a_v2.
    Decodes the returned hex-encoded MP3 audio from the synchronous response.
    """
    url = f"{MINIMAX_BASE_URL}/t2a_v2"
    headers = _get_headers()
    headers["Content-Type"] = "application/json"

    payload = {
        "model": "speech-2.8-hd",
        "text": text,
        "stream": False,
        "language_boost": "auto",
        "voice_setting": {
            "voice_id": voice_id,
            "speed": float(speed),
            "vol": float(volume),
            "pitch": int(pitch),
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }

    logger.info(f"Generating speech for text ({len(text)} chars) with voice '{voice_id}'...")
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()
    resp_data = response.json()

    # MiniMax returns hex-encoded audio in resp_data["data"]["audio"]
    audio_hex = resp_data.get("data", {}).get("audio", "")
    if not audio_hex:
        # Check if base64 or direct binary was provided
        raise ValueError(f"No audio stream returned in MiniMax t2a_v2 response: {resp_data.get('base_resp')}")

    try:
        audio_bytes = bytes.fromhex(audio_hex)
    except Exception as e:
        raise ValueError(f"Failed to decode hex audio stream: {e}")

    logger.info(f"Successfully decoded {len(audio_bytes)} bytes of MP3 audio.")
    return {
        "audio_bytes": audio_bytes,
        "raw_response": resp_data,
        "duration_seconds": resp_data.get("data", {}).get("extra_info", {}).get("audio_length", 0) / 1000.0
    }


def delete_voice(voice_id: str) -> Dict[str, Any]:
    """
    Delete a cloned voice model using MiniMax Voice Management API.
    """
    url = f"{MINIMAX_BASE_URL}/voice_delete"
    headers = _get_headers()
    headers["Content-Type"] = "application/json"

    payload = {
        "voice_id": voice_id
    }

    logger.info(f"Requesting deletion of voice '{voice_id}' from MiniMax...")
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=60,
    )

    response.raise_for_status()
    return response.json()
