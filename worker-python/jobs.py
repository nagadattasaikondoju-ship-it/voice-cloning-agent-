"""
Handlers for the Redis queues filled by the Rust API:

    voice_clone_jobs  -> prepare the reference clip (the "clone")
    speech_jobs       -> synthesize text in that voice, store an MP3
    delete_voice_jobs -> remove the reference clip

Every job ends in a terminal DB state ('ready', or 'failed' with a reason).
"""
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

import tts
from audio_utils import finalize, prepare_reference
from settings import DATABASE_URL
from storage import path_for

logger = logging.getLogger(__name__)


def _execute(sql: str, params: tuple) -> None:
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


def _fetch_one(sql: str, params: tuple) -> Optional[Dict[str, Any]]:
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def _reason(err: Exception) -> str:
    msg = str(err) or err.__class__.__name__
    if "out of memory" in msg.lower():
        msg = "The GPU ran out of memory. Try shorter text, or set CHATTERBOX_DEVICE=cpu."
    return msg[:500]


def process_voice_clone_job(job: Dict[str, Any]) -> None:
    clone_id, voice_id = job["job_id"], job["voice_id"]
    logger.info(f"[clone {clone_id}] preparing reference for {voice_id}")
    _execute("UPDATE voice_clones SET status = 'processing', error_message = NULL WHERE id = %s", (clone_id,))
    try:
        ref_key = f"references/{voice_id}.wav"
        seconds = prepare_reference(path_for(job["sample_storage_path"]), path_for(ref_key))
        _execute(
            "UPDATE voice_clones SET status = 'ready', reference_audio_key = %s WHERE id = %s",
            (ref_key, clone_id),
        )
        logger.info(f"[clone {clone_id}] ready ({seconds:.1f} s reference)")
    except Exception as e:
        logger.error(f"[clone {clone_id}] failed: {e}")
        _execute("UPDATE voice_clones SET status = 'failed', error_message = %s WHERE id = %s", (_reason(e), clone_id))


def process_speech_job(job: Dict[str, Any]) -> None:
    job_id = job["job_id"]
    logger.info(f"[speech {job_id}] {len(job['text'])} chars, lang={job.get('language', 'en')}")
    _execute("UPDATE speech_jobs SET status = 'processing' WHERE id = %s", (job_id,))
    try:
        clone = _fetch_one(
            "SELECT reference_audio_key FROM voice_clones WHERE voice_id = %s AND user_id = %s AND deleted_at IS NULL",
            (job["voice_id"], job["user_id"]),
        )
        if not clone or not clone["reference_audio_key"]:
            raise ValueError("This voice no longer exists or was never prepared. Re-create it.")

        out_key = f"generated/{job_id}.mp3"
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.wav"
            tts.synthesize(path_for(clone["reference_audio_key"]), job["text"], job.get("language", "en"), raw)
            duration = finalize(raw, path_for(out_key), float(job.get("speed", 1.0)), float(job.get("volume", 1.0)))
        size = path_for(out_key).stat().st_size

        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generated_audio (id, speech_job_id, user_id, storage_key, duration_seconds,
                                             file_size_bytes, mime_type)
                VALUES (%s, %s, %s, %s, %s, %s, 'audio/mpeg')
                """,
                (str(uuid.uuid4()), job_id, job["user_id"], out_key, duration, size),
            )
            cur.execute("UPDATE speech_jobs SET status = 'ready', error_message = NULL WHERE id = %s", (job_id,))
        logger.info(f"[speech {job_id}] ready ({duration} s)")
    except Exception as e:
        logger.error(f"[speech {job_id}] failed: {e}")
        _execute("UPDATE speech_jobs SET status = 'failed', error_message = %s WHERE id = %s", (_reason(e), job_id))


def delete_voice_job(job: Dict[str, Any]) -> None:
    path_for(f"references/{job['voice_id']}.wav").unlink(missing_ok=True)
    logger.info(f"Deleted reference for {job['voice_id']}")
