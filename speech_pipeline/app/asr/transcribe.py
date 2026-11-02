import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from app.config import settings
from app.audio.vad import process_vad_and_create_chunks
from app.audio.timestamps import map_chunk_timestamps_to_original, merge_and_format_transcript
from app.asr.whisper_engine import transcribe_chunk_file
from app.storage.database import (
    update_recording_status,
    update_recording_result,
    add_chunks,
    add_segments,
    get_recording
)
from app.storage.files import (
    get_wav_16k_path,
    get_vad_metadata_path,
    get_transcript_path,
    get_result_json_path,
    save_json
)

logger = logging.getLogger("speech_pipeline.transcribe")


def _transcribe_single_chunk_with_retry(
    chunk: Dict[str, Any],
    language: Optional[str] = None,
    max_retries: int = 3
) -> Tuple[Dict[str, Any], Optional[str], float, List[Dict[str, Any]]]:
    """
    Transcribes a single chunk with retry logic for transient model or IO errors.
    """
    chunk_file = chunk["chunk_file_path"]
    is_silent = bool(chunk.get("is_silent", 0))

    # If VAD explicitly flagged this chunk as silent, skip whisper inference
    if is_silent:
        logger.info(f"Chunk {chunk['chunk_index']} flagged as silent, skipping ASR inference.")
        return chunk, language or "en", 1.0, []

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            detected_lang, lang_prob, segments = transcribe_chunk_file(
                chunk_file,
                language=language,
                word_timestamps=settings.whisper_word_timestamps
            )
            return chunk, detected_lang, lang_prob, segments
        except Exception as e:
            last_error = e
            logger.warning(
                f"[Attempt {attempt}/{max_retries}] Transcription error on {chunk_file}: {e}"
            )
            time.sleep(0.5 * attempt)

    logger.error(f"Failed to transcribe chunk {chunk_file} after {max_retries} retries: {last_error}")
    return chunk, language or "en", 0.0, []


def run_transcription_pipeline(
    recording_id: str,
    language: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the complete speech-to-text pipeline for a recording:
    1. VAD speech region detection and 5-second chunking.
    2. Chunk transcription (sequential by default, parallel if configured).
    3. Timestamp restoration to original recording timeline.
    4. Paragraph merging and hallucination removal.
    5. Persistence to SQLite and storage files.
    """
    start_time = time.time()
    logger.info(f"[{recording_id}] Starting speech pipeline execution...")

    # Step 1: Update status to processing
    update_recording_status(recording_id, "processing")

    try:
        wav_path = get_wav_16k_path(recording_id)
        if not wav_path.exists():
            raise FileNotFoundError(f"16kHz audio not found at {wav_path}")

        # Step 2: Run Silero VAD & chunking
        vad_start = time.time()
        chunks_meta, vad_metadata = process_vad_and_create_chunks(wav_path, recording_id)
        vad_duration = time.time() - vad_start
        logger.info(f"[{recording_id}] VAD & chunking finished in {vad_duration:.2f}s ({len(chunks_meta)} chunks)")

        # Persist chunks to database
        add_chunks(recording_id, chunks_meta)

        # Step 3: Transcribe chunks
        asr_start = time.time()
        raw_results: List[Tuple[Dict[str, Any], Optional[str], float, List[Dict[str, Any]]]] = []

        if settings.parallel_workers > 1 and len(chunks_meta) > 1:
            logger.info(f"[{recording_id}] Running parallel transcription with {settings.parallel_workers} workers")
            with ThreadPoolExecutor(max_workers=settings.parallel_workers) as executor:
                future_to_chunk = {
                    executor.submit(_transcribe_single_chunk_with_retry, c, language): c
                    for c in chunks_meta
                }
                for future in as_completed(future_to_chunk):
                    raw_results.append(future.result())
            # Re-sort results by chunk_index
            raw_results.sort(key=lambda r: r[0]["chunk_index"])
        else:
            # Sequential execution for maximum accuracy
            logger.info(f"[{recording_id}] Running sequential chunk transcription")
            for c in chunks_meta:
                res = _transcribe_single_chunk_with_retry(c, language)
                raw_results.append(res)

        asr_duration = time.time() - asr_start
        logger.info(f"[{recording_id}] ASR transcription finished in {asr_duration:.2f}s")

        # Step 4: Map local timestamps to original recording timeline
        primary_language = language
        primary_lang_prob = 1.0
        all_mapped_segments = []

        for chunk, det_lang, lang_prob, chunk_segments in raw_results:
            if not primary_language and det_lang:
                primary_language = det_lang
                primary_lang_prob = lang_prob

            mapped = map_chunk_timestamps_to_original(chunk, chunk_segments)
            all_mapped_segments.extend(mapped)

        # Step 5: Merge transcript and insert paragraph breaks
        full_transcript, final_segments = merge_and_format_transcript(
            all_mapped_segments,
            paragraph_silence_threshold_s=settings.paragraph_silence_threshold_s
        )

        # Step 6: Persist segments and results to SQLite & storage
        add_segments(recording_id, final_segments)

        audio_duration = vad_metadata.get("total_audio_duration_s", 0.0)
        vad_meta_path = str(get_vad_metadata_path(recording_id))

        update_recording_result(
            recording_id=recording_id,
            status="completed",
            duration_seconds=audio_duration,
            language=primary_language or "en",
            language_probability=round(primary_lang_prob, 3),
            full_transcript=full_transcript,
            vad_metadata_path=vad_meta_path
        )

        # Save transcript text file
        transcript_file = get_transcript_path(recording_id)
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(full_transcript)

        # Save full result JSON
        result_payload = {
            "recording_id": recording_id,
            "status": "completed",
            "duration_seconds": audio_duration,
            "language": primary_language or "en",
            "language_probability": round(primary_lang_prob, 3),
            "full_transcript": full_transcript,
            "segments": final_segments,
            "chunk_files": [c["chunk_file_path"] for c in chunks_meta]
        }
        save_json(get_result_json_path(recording_id), result_payload)

        total_pipeline_time = time.time() - start_time
        logger.info(
            f"[{recording_id}] Speech pipeline completed successfully in {total_pipeline_time:.2f}s! "
            f"Transcript: {len(full_transcript)} chars, {len(final_segments)} segments."
        )
        return result_payload

    except Exception as e:
        logger.error(f"[{recording_id}] Pipeline execution failed: {e}", exc_info=True)
        update_recording_status(recording_id, "failed", error_message=str(e))
        raise e
