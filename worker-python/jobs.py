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
from audio_utils import REFERENCE_MAX_SECONDS, finalize, prepare_reference
from settings import DATABASE_URL
import storage

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
    return (str(err) or err.__class__.__name__)[:500]


def process_voice_clone_job(job: Dict[str, Any]) -> None:
    clone_id, voice_id = job["job_id"], job["voice_id"]
    logger.info(f"[clone {clone_id}] preparing reference for {voice_id}")
    _execute("UPDATE voice_clones SET status = 'processing', error_message = NULL WHERE id = %s", (clone_id,))
    try:
        ref_key = f"references/{voice_id}.wav"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / ("sample" + Path(job["sample_storage_path"]).suffix)
            if not storage.load_to(job["sample_storage_path"], src):
                raise ValueError("The recording for this voice is missing. Create the voice again.")
            ref = Path(tmp) / "reference.wav"
            seconds = prepare_reference(src, ref)
            storage.save(ref_key, job["user_id"], "audio/wav", ref.read_bytes())
        # The sample is the consent recording, so its verified transcript says what is in it.
        # Skip it if the clip was cut at the length limit (the text would no longer match).
        text = (job.get("reference_text") or "").strip()
        if text and seconds < REFERENCE_MAX_SECONDS - 0.1 and len(text) <= 500:
            storage.save(f"references/{voice_id}.txt", job["user_id"], "text/plain", text.encode("utf-8"))
        else:
            storage.delete(f"references/{voice_id}.txt")
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
    logger.info(f"[speech {job_id}] {len(job['text'])} chars")
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
            ref = Path(tmp) / "reference.wav"
            if not storage.load_to(clone["reference_audio_key"], ref):
                raise ValueError("This voice's reference clip is missing. Re-create the voice.")
            ref_text = storage.load(clone["reference_audio_key"].rsplit(".", 1)[0] + ".txt")
            if ref_text:
                ref.with_suffix(".txt").write_bytes(ref_text)  # tts.synthesize reads it from here
            raw, mp3 = Path(tmp) / "raw.wav", Path(tmp) / "out.mp3"
            tts.synthesize(ref, job["text"], raw)
            duration = finalize(raw, mp3, float(job.get("speed", 1.0)), float(job.get("volume", 1.0)))
            data = mp3.read_bytes()
        storage.save(out_key, job["user_id"], "audio/mpeg", data)

        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generated_audio (id, speech_job_id, user_id, storage_key, duration_seconds,
                                             file_size_bytes, mime_type)
                VALUES (%s, %s, %s, %s, %s, %s, 'audio/mpeg')
                """,
                (str(uuid.uuid4()), job_id, job["user_id"], out_key, duration, len(data)),
            )
            cur.execute("UPDATE speech_jobs SET status = 'ready', error_message = NULL WHERE id = %s", (job_id,))
        logger.info(f"[speech {job_id}] ready ({duration} s)")
    except Exception as e:
        logger.error(f"[speech {job_id}] failed: {e}")
        _execute("UPDATE speech_jobs SET status = 'failed', error_message = %s WHERE id = %s", (_reason(e), job_id))


def delete_voice_job(job: Dict[str, Any]) -> None:
    storage.delete(f"references/{job['voice_id']}.wav", f"references/{job['voice_id']}.txt")
    logger.info(f"Deleted reference for {job['voice_id']}")
