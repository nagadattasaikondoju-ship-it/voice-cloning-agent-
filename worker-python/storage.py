import os
from pathlib import Path
from typing import Optional
import logging

from settings import (
    STORAGE_TYPE,
    STORAGE_DIR,
    S3_ENDPOINT,
    S3_BUCKET,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
)

logger = logging.getLogger(__name__)

# Ensure local directories exist
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "samples").mkdir(parents=True, exist_ok=True)
(STORAGE_DIR / "generated").mkdir(parents=True, exist_ok=True)


def get_local_file_path(storage_key: str) -> str:
    """
    Given a storage key (e.g. 'samples/uuid.wav'), return the absolute local path.
    If S3 storage is enabled, downloads the object if not cached locally.
    """
    local_path = (STORAGE_DIR / storage_key).resolve()

    if STORAGE_TYPE == "s3" and S3_ENDPOINT and S3_ACCESS_KEY:
        import boto3

        if not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            s3 = boto3.client(
                "s3",
                endpoint_url=S3_ENDPOINT,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            logger.info(f"Downloading s3://{S3_BUCKET}/{storage_key} to {local_path}...")
            s3.download_file(S3_BUCKET, storage_key, str(local_path))

    return str(local_path)


def save_generated_audio(job_id: str, audio_bytes: bytes) -> str:
    """
    Saves generated MP3 audio bytes to private storage.
    Returns the relative storage_key (e.g. 'generated/job_id.mp3').
    """
    filename = f"{job_id}.mp3"
    storage_key = f"generated/{filename}"
    local_path = STORAGE_DIR / storage_key

    local_path.parent.mkdir(parents=True, exist_ok=True)

    with open(local_path, "wb") as f:
        f.write(audio_bytes)

    if STORAGE_TYPE == "s3" and S3_ENDPOINT and S3_ACCESS_KEY:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
        )
        logger.info(f"Uploading generated audio to s3://{S3_BUCKET}/{storage_key}...")
        s3.upload_file(str(local_path), S3_BUCKET, storage_key)

    logger.info(f"Saved generated audio to storage key: {storage_key}")
    return storage_key


def delete_stored_file(storage_key: str) -> None:
    """
    Removes a file from local and S3 storage.
    """
    local_path = STORAGE_DIR / storage_key
    if local_path.exists():
        try:
            local_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove local file {local_path}: {e}")

    if STORAGE_TYPE == "s3" and S3_ENDPOINT and S3_ACCESS_KEY:
        import boto3
        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=S3_ENDPOINT,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            s3.delete_object(Bucket=S3_BUCKET, Key=storage_key)
        except Exception as e:
            logger.warning(f"Failed to delete S3 object {storage_key}: {e}")
