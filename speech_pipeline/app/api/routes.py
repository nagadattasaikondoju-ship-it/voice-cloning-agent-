import os
import uuid
import logging
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    Body,
    BackgroundTasks,
    HTTPException,
    status
)
from fastapi.responses import FileResponse

from app.config import settings
from app.schemas import (
    RecordingResponse,
    CreateRecordingResponse,
    ProcessJobResponse,
    Base64RecordingRequest,
    SegmentResponse
)
from app.audio.recorder import decode_base64_audio, save_audio_bytes
from app.audio.preprocess import convert_to_wav_16k_mono, AudioProcessingError
from app.asr.transcribe import run_transcription_pipeline
from app.asr.whisper_engine import get_whisper_engine
from app.storage.database import (
    create_recording,
    get_recording,
    get_recording_segments,
    get_recording_chunks,
    delete_recording
)
from app.storage.files import (
    get_raw_audio_path,
    get_wav_16k_path,
    delete_recording_files
)

logger = logging.getLogger("speech_pipeline.routes")

router = APIRouter(prefix="/api/v1", tags=["recordings"])


@router.post(
    "/recordings",
    response_model=CreateRecordingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload audio file or base64 data for ingestion"
)
async def create_new_recording(
    file: Optional[UploadFile] = File(None),
    language: Optional[str] = Form(None),
    base64_payload: Optional[Base64RecordingRequest] = Body(None)
):
    """
    Ingests an audio recording either via multipart/form-data file upload
    or base64 encoded audio in JSON body.
    Converts audio to 16 kHz mono 16-bit PCM WAV and sets status to 'queued'.
    """
    recording_id = str(uuid.uuid4())
    logger.info(f"Ingesting new recording: id={recording_id}")

    try:
        if file is not None:
            # File upload mode
            filename = file.filename or "recording.wav"
            ext = Path(filename).suffix.lstrip(".") or "wav"
            raw_path = get_raw_audio_path(recording_id, ext)
            
            content = await file.read()
            save_audio_bytes(content, raw_path)
            req_language = language

        elif base64_payload is not None:
            # Base64 JSON payload mode
            raw_bytes, ext = decode_base64_audio(base64_payload.audio_base64)
            filename = base64_payload.filename or f"recording.{ext}"
            raw_path = get_raw_audio_path(recording_id, ext)
            
            save_audio_bytes(raw_bytes, raw_path)
            req_language = base64_payload.language

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either an audio file upload or base64 JSON payload must be provided."
            )

        # Standardize audio to 16kHz mono WAV
        wav_16k_path = get_wav_16k_path(recording_id)
        duration = convert_to_wav_16k_mono(raw_path, wav_16k_path)

        # Store in SQLite database with status 'queued'
        create_recording(
            recording_id=recording_id,
            filename=filename,
            raw_audio_path=str(raw_path),
            wav_16k_path=str(wav_16k_path),
            duration_seconds=duration,
            language=req_language
        )

        return CreateRecordingResponse(
            recording_id=recording_id,
            status="queued",
            duration_seconds=round(duration, 2),
            message="Audio successfully converted to 16kHz mono WAV and queued."
        )

    except AudioProcessingError as e:
        delete_recording_files(recording_id)
        logger.error(f"Audio processing error for {recording_id}: {e}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        delete_recording_files(recording_id)
        logger.error(f"Unexpected error ingesting {recording_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ingestion failed: {e}")


@router.post(
    "/recordings/{recording_id}/process",
    response_model=ProcessJobResponse,
    summary="Start background speech transcription job"
)
async def process_recording(
    recording_id: str,
    background_tasks: BackgroundTasks,
    language: Optional[str] = None
):
    """
    Launches Silero VAD and Whisper transcription as a non-blocking background job.
    """
    rec = get_recording(recording_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording '{recording_id}' not found."
        )

    if rec["status"] == "processing":
        return ProcessJobResponse(
            recording_id=recording_id,
            status="processing",
            message="Job is already actively processing in the background."
        )

    chosen_language = language or rec.get("language")

    # Launch background task
    background_tasks.add_task(
        run_transcription_pipeline,
        recording_id=recording_id,
        language=chosen_language
    )

    return ProcessJobResponse(
        recording_id=recording_id,
        status="processing",
        message="Background transcription job successfully initiated."
    )


@router.get(
    "/recordings/{recording_id}",
    response_model=RecordingResponse,
    summary="Get recording status, full transcript, and timestamped segments"
)
async def get_recording_details(recording_id: str):
    """
    Retrieves full details for a recording, including status, full transcript,
    timestamped segments, and chunk file paths.
    """
    rec = get_recording(recording_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording '{recording_id}' not found."
        )

    segments_rows = get_recording_segments(recording_id)
    chunks_rows = get_recording_chunks(recording_id)

    segments_res = [
        SegmentResponse(
            segment_id=s["segment_id"],
            start=s["start_time"],
            end=s["end_time"],
            text=s["text"],
            confidence=s.get("confidence"),
            words=s.get("words")
        )
        for s in segments_rows
    ]

    chunk_files = [c["chunk_file_path"] for c in chunks_rows]

    return RecordingResponse(
        recording_id=rec["recording_id"],
        status=rec["status"],
        duration_seconds=rec["duration_seconds"],
        language=rec["language"],
        language_probability=rec["language_probability"],
        full_transcript=rec["full_transcript"],
        segments=segments_res,
        chunk_files=chunk_files,
        created_at=rec["created_at"],
        error_message=rec["error_message"]
    )


@router.get(
    "/recordings/{recording_id}/audio",
    summary="Stream original standardized 16kHz WAV audio"
)
async def stream_recording_audio(recording_id: str):
    """
    Streams the standardized 16kHz mono WAV file for playback in audio players.
    """
    rec = get_recording(recording_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording '{recording_id}' not found."
        )

    wav_path = Path(rec["wav_16k_path"])
    if not wav_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file missing on disk."
        )

    return FileResponse(
        path=str(wav_path),
        media_type="audio/wav",
        filename=f"recording_{recording_id}.wav"
    )


@router.delete(
    "/recordings/{recording_id}",
    summary="Delete recording and all associated files and database records"
)
async def remove_recording(recording_id: str):
    """
    Deletes the recording from SQLite and purges all storage files from disk.
    """
    rec = get_recording(recording_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording '{recording_id}' not found."
        )

    db_deleted = delete_recording(recording_id)
    files_deleted = delete_recording_files(recording_id)

    return {
        "deleted": db_deleted,
        "files_removed": files_deleted,
        "recording_id": recording_id,
        "message": "Recording and all associated files deleted successfully."
    }


@router.get("/health", summary="Health check and engine status")
async def health_check():
    """Returns engine health and model status."""
    engine = get_whisper_engine()
    return {
        "status": "healthy",
        "whisper_info": engine.info,
        "settings": {
            "vad_sample_rate": settings.vad_sample_rate,
            "vad_threshold": settings.vad_threshold,
            "max_speech_duration_s": settings.vad_max_speech_duration_s,
            "min_silence_duration_ms": settings.vad_min_silence_duration_ms,
            "parallel_workers": settings.parallel_workers
        }
    }
