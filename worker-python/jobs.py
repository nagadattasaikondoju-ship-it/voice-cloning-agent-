import time
import logging
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any

from settings import DATABASE_URL, MINIMAX_API_KEY
from storage import get_local_file_path, save_generated_audio
from minimax_client import upload_voice_sample, create_voice_clone, generate_speech, delete_voice

logger = logging.getLogger(__name__)


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def process_voice_clone_job(job: Dict[str, Any]) -> None:
    """
    Executes the MiniMax Voice Cloning pipeline:
    1. Retrieve sample file from storage.
    2. Upload to POST /v1/files/upload with purpose=voice_clone.
    3. Call POST /v1/voice_clone with file_id and requested_voice_id.
    4. Update PostgreSQL status to 'ready' or 'failed'.
    """
    job_id = job["job_id"]
    user_id = job["user_id"]
    sample_storage_path = job["sample_storage_path"]
    requested_voice_id = job["requested_voice_id"]
    display_name = job.get("display_name", "Cloned Voice")

    logger.info(f"[JOB:{job_id}] Processing voice clone job for voice_id '{requested_voice_id}'...")

    # Update status to 'processing'
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE voice_clones SET status = 'processing' WHERE id = %s AND user_id = %s",
                (job_id, user_id),
            )
            conn.commit()

    max_retries = 3
    attempt = 0
    file_id = None

    while attempt < max_retries:
        attempt += 1
        try:
            # 1. Resolve local path
            local_sample_path = get_local_file_path(sample_storage_path)

            if not MINIMAX_API_KEY or MINIMAX_API_KEY == "your_minimax_api_key_here":
                # Simulated demo / offline pass when API key is not yet provided by user
                logger.warning(f"[JOB:{job_id}] Running in demo mode without real MiniMax API key.")
                time.sleep(2)
                file_id = 99999999
            else:
                # 2. Upload source audio sample
                file_id = upload_voice_sample(local_sample_path)

                # 3. Create voice clone
                create_voice_clone(
                    file_id=file_id,
                    voice_id=requested_voice_id,
                    preview_text=f"This is an approved preview of {display_name}."
                )

            # Mark ready in PostgreSQL
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE voice_clones SET status = 'ready' WHERE id = %s",
                        (job_id,)
                    )
                    conn.commit()

            logger.info(f"[JOB:{job_id}] Voice clone '{requested_voice_id}' is successfully deployed and READY!")
            return

        except Exception as e:
            logger.error(f"[JOB:{job_id}] Error in clone attempt {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                backoff = 2 ** attempt
                logger.info(f"Retrying in {backoff} seconds...")
                time.sleep(backoff)
            else:
                # Permanent failure
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE voice_clones SET status = 'failed' WHERE id = %s",
                            (job_id,)
                        )
                        conn.commit()
                logger.error(f"[JOB:{job_id}] Voice clone job failed permanently.")


def process_speech_job(job: Dict[str, Any]) -> None:
    """
    Executes the MiniMax Speech Synthesis pipeline:
    1. Call POST /v1/t2a_v2 with custom voice_id and speech parameters.
    2. Decode returned hex audio into MP3 bytes.
    3. Save MP3 to private storage.
    4. Insert generated_audio row and mark speech_jobs as 'ready'.
    """
    job_id = job["job_id"]
    user_id = job["user_id"]
    minimax_voice_id = job["minimax_voice_id"]
    text = job["text"]
    speed = job.get("speed", 1.0)
    volume = job.get("volume", 1.0)
    pitch = job.get("pitch", 0)

    logger.info(f"[SPEECH:{job_id}] Generating speech with voice '{minimax_voice_id}' for {len(text)} chars...")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE speech_jobs SET status = 'processing' WHERE id = %s",
                (job_id,)
            )
            conn.commit()

    try:
        if not MINIMAX_API_KEY or MINIMAX_API_KEY == "your_minimax_api_key_here":
            logger.warning(f"[SPEECH:{job_id}] Demo mode: Generating fallback silent/tone MP3 bytes.")
            # Minimal MP3 frame representation
            audio_bytes = b"\xff\xfb\x90\x00" * 256
            duration = 3.0
        else:
            result = generate_speech(
                voice_id=minimax_voice_id,
                text=text,
                speed=speed,
                volume=volume,
                pitch=pitch,
            )
            audio_bytes = result["audio_bytes"]
            duration = result.get("duration_seconds", 5.0)

        # Save to private storage
        storage_key = save_generated_audio(str(job_id), audio_bytes)
        file_size = len(audio_bytes)

        generated_id = str(uuid.uuid4())

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO generated_audio (id, speech_job_id, user_id, storage_key, duration_seconds, file_size_bytes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (generated_id, job_id, user_id, storage_key, duration, file_size)
                )
                cur.execute(
                    "UPDATE speech_jobs SET status = 'ready' WHERE id = %s",
                    (job_id,)
                )
                conn.commit()

        logger.info(f"[SPEECH:{job_id}] Audio synthesized and ready. Storage key: {storage_key}")

    except Exception as e:
        logger.error(f"[SPEECH:{job_id}] Failed to generate speech: {e}")
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE speech_jobs SET status = 'failed', error_message = %s WHERE id = %s",
                    (str(e), job_id)
                )
                conn.commit()


def delete_voice_job(job: Dict[str, Any]) -> None:
    """
    Calls the MiniMax voice management deletion endpoint.
    """
    minimax_voice_id = job["minimax_voice_id"]
    logger.info(f"Purging voice '{minimax_voice_id}' from MiniMax...")
    try:
        if MINIMAX_API_KEY and MINIMAX_API_KEY != "your_minimax_api_key_here":
            delete_voice(minimax_voice_id)
            logger.info(f"Voice '{minimax_voice_id}' purged from MiniMax successfully.")
    except Exception as e:
        logger.error(f"Failed to delete voice '{minimax_voice_id}' on MiniMax: {e}")
