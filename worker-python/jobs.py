"""
Job handlers for the three Redis queues pushed by the Rust API:

    voice_clone_jobs  -> process_voice_clone_job
    speech_jobs       -> process_speech_job
    delete_voice_jobs -> delete_voice_job

Every job ends in a terminal DB state ('ready' or 'failed' with error_message) so the
dashboard never polls forever. There is no simulated "demo" success: an engine without
credentials fails with a clear message.
"""
import logging
import os
import tempfile
import time
import uuid
from typing import Any, Callable, Dict, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from audio_utils import duration_seconds, to_mp3_bytes
from engines import get_engine
from engines.errors import PermanentError
from settings import DATABASE_URL
from storage import get_local_file_path, save_generated_audio

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def _execute(sql: str, params: tuple) -> None:
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


def _fetch_one(sql: str, params: tuple) -> Optional[Dict[str, Any]]:
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def _user_message(err: Exception) -> str:
    msg = str(err) or err.__class__.__name__
    return msg[:500]


def _with_retries(label: str, fn: Callable[[], Any]) -> Any:
    last: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - surfaced to the user after retries
            last = e
            logger.warning(f"[{label}] attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            if attempt < MAX_ATTEMPTS and not isinstance(e, (ValueError, FileNotFoundError, PermanentError)):
                time.sleep(2 ** attempt)
            else:
                break
    raise last  # type: ignore[misc]


def process_voice_clone_job(job: Dict[str, Any]) -> None:
    clone_id = job["job_id"]
    engine_name = job.get("engine", "minimax")
    label = f"CLONE:{clone_id}:{engine_name}"
    logger.info(f"[{label}] starting")
    _execute("UPDATE voice_clones SET status = 'processing', error_message = NULL WHERE id = %s", (clone_id,))

    try:
        engine = get_engine(engine_name)
        sample_path = get_local_file_path(job["sample_storage_path"])
        if not os.path.isfile(sample_path):
            raise FileNotFoundError("Voice sample file is missing from storage")
        result = _with_retries(
            label, lambda: engine.clone(sample_path, job["requested_voice_id"], job.get("display_name", "Voice"))
        )
        _execute(
            """
            UPDATE voice_clones
            SET status = 'ready', error_message = NULL,
                provider_voice_id = %s, reference_audio_key = %s, reference_text = %s
            WHERE id = %s
            """,
            (result.get("provider_voice_id"), result.get("reference_audio_key"), result.get("reference_text"), clone_id),
        )
        logger.info(f"[{label}] ready")
    except Exception as e:
        logger.error(f"[{label}] failed: {e}")
        _execute(
            "UPDATE voice_clones SET status = 'failed', error_message = %s WHERE id = %s",
            (_user_message(e), clone_id),
        )


def process_speech_job(job: Dict[str, Any]) -> None:
    job_id = job["job_id"]
    engine_name = job.get("engine", "minimax")
    label = f"SPEECH:{job_id}:{engine_name}"
    logger.info(f"[{label}] {len(job.get('text', ''))} chars")
    _execute("UPDATE speech_jobs SET status = 'processing' WHERE id = %s", (job_id,))

    try:
        clone_row = _fetch_one(
            """
            SELECT provider_voice_id, reference_audio_key, reference_text
            FROM voice_clones WHERE voice_id = %s AND user_id = %s AND deleted_at IS NULL
            """,
            (job["voice_id"], job["user_id"]),
        )
        if not clone_row:
            raise ValueError("Voice clone no longer exists")

        engine = get_engine(engine_name)
        raw_audio = _with_retries(label, lambda: engine.synthesize(job, clone_row))

        # Normalize every engine's output to MP3 for storage and playback.
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = os.path.join(tmp, "raw_audio")
            with open(raw_path, "wb") as f:
                f.write(raw_audio)
            is_mp3 = raw_audio[:3] == b"ID3" or (len(raw_audio) > 1 and raw_audio[0] == 0xFF and raw_audio[1] & 0xE0 == 0xE0)
            mp3_bytes = raw_audio if is_mp3 else to_mp3_bytes(raw_path)
            mp3_path = os.path.join(tmp, "out.mp3")
            with open(mp3_path, "wb") as f:
                f.write(mp3_bytes)
            duration = duration_seconds(mp3_path)

        storage_key = save_generated_audio(str(job_id), mp3_bytes)
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generated_audio (id, speech_job_id, user_id, storage_key, duration_seconds,
                                             file_size_bytes, mime_type)
                VALUES (%s, %s, %s, %s, %s, %s, 'audio/mpeg')
                """,
                (str(uuid.uuid4()), job_id, job["user_id"], storage_key, duration, len(mp3_bytes)),
            )
            cur.execute("UPDATE speech_jobs SET status = 'ready', error_message = NULL WHERE id = %s", (job_id,))
        logger.info(f"[{label}] ready ({duration}s, {len(mp3_bytes)} bytes)")
    except Exception as e:
        logger.error(f"[{label}] failed: {e}")
        _execute(
            "UPDATE speech_jobs SET status = 'failed', error_message = %s WHERE id = %s",
            (_user_message(e), job_id),
        )


def delete_voice_job(job: Dict[str, Any]) -> None:
    engine_name = job.get("engine", "minimax")
    try:
        get_engine(engine_name).delete(job["voice_id"], job.get("provider_voice_id"))
        logger.info(f"Deleted voice '{job['voice_id']}' from {engine_name}")
    except Exception as e:
        logger.error(f"Provider delete failed for '{job['voice_id']}' ({engine_name}): {e}")
