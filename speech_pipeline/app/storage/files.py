"""
On-disk layout for a recording:

    <storage_dir>/recordings/<recording_id>/
        raw.<ext>            original upload
        audio_16k.wav        standardized 16 kHz mono PCM
        chunks/chunk_001.wav VAD speech chunks
        vad_metadata.json
        transcript.txt
        result.json
"""
import json
import shutil
import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("speech_pipeline.storage.files")


def _safe_id(recording_id: str) -> str:
    # Recording ids are UUIDs generated server-side; refuse anything that could escape the directory.
    if not recording_id or "/" in recording_id or "\\" in recording_id or ".." in recording_id:
        raise ValueError(f"Invalid recording id: {recording_id!r}")
    return recording_id


def get_recording_dir(recording_id: str) -> Path:
    path = settings.storage_dir / "recordings" / _safe_id(recording_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_raw_audio_path(recording_id: str, ext: str) -> Path:
    ext = (ext or "wav").lower().lstrip(".")
    if not ext.isalnum() or len(ext) > 5:
        ext = "bin"
    return get_recording_dir(recording_id) / f"raw.{ext}"


def get_wav_16k_path(recording_id: str) -> Path:
    return get_recording_dir(recording_id) / "audio_16k.wav"


def get_chunk_path(recording_id: str, chunk_index: int) -> Path:
    chunk_dir = get_recording_dir(recording_id) / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    return chunk_dir / f"chunk_{chunk_index + 1:03d}.wav"


def get_vad_metadata_path(recording_id: str) -> Path:
    return get_recording_dir(recording_id) / "vad_metadata.json"


def get_transcript_path(recording_id: str) -> Path:
    return get_recording_dir(recording_id) / "transcript.txt"


def get_result_json_path(recording_id: str) -> Path:
    return get_recording_dir(recording_id) / "result.json"


def save_json(path: Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


def delete_recording_files(recording_id: str) -> bool:
    """Removes the recording directory. Returns True if anything was deleted."""
    try:
        path = settings.storage_dir / "recordings" / _safe_id(recording_id)
    except ValueError:
        return False
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False
