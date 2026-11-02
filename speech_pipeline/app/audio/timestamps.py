import re
import logging
from typing import List, Dict, Any, Tuple
from app.config import settings

logger = logging.getLogger("speech_pipeline.timestamps")

# Known Whisper repetitive hallucinations on silence or low-energy audio
COMMON_HALLUCINATIONS = {
    "thank you",
    "thank you.",
    "thank you very much.",
    "thanks for watching",
    "thanks for watching.",
    "thanks for watching!",
    "subscribe to my channel",
    "subscribe to my channel.",
    "see you next time",
    "see you next time.",
    "bye.",
    "bye",
    "you",
    "silence",
    "[silence]",
    "[music]",
    "(music)",
    "[applause]",
    "like and subscribe",
}


def is_hallucinated_segment(text: str, is_chunk_silent: bool = False, rms_energy: float = 1.0) -> bool:
    """
    Detects if a transcribed segment text is likely an empty or hallucinated artifact.
    """
    clean_text = text.strip().lower()
    
    if not clean_text:
        return True

    # If chunk audio energy was negligible and text is a known hallucination
    if is_chunk_silent or rms_energy < 0.005:
        if clean_text in COMMON_HALLUCINATIONS:
            return True
        if len(clean_text) < 4:
            return True

    # If text is in known hallucination list and very short
    if clean_text in COMMON_HALLUCINATIONS and len(clean_text) < 25:
        if is_chunk_silent or rms_energy < 0.01:
            return True

    return False


def map_chunk_timestamps_to_original(
    chunk_meta: Dict[str, Any],
    chunk_segments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Restores original timeline timestamps for segments and word timestamps within a chunk.
    chunk_meta contains 'start_s' indicating the chunk's offset in original recording.
    """
    offset_s = chunk_meta["start_s"]
    is_silent = bool(chunk_meta.get("is_silent", 0))
    rms_energy = chunk_meta.get("rms_energy", 1.0)

    mapped_segments = []
    for seg in chunk_segments:
        text = seg.get("text", "").strip()
        if is_hallucinated_segment(text, is_chunk_silent=is_silent, rms_energy=rms_energy):
            logger.info(f"Filtered hallucinated/silent segment: '{text}' (RMS: {rms_energy:.4f})")
            continue

        raw_start = seg.get("start", 0.0)
        raw_end = seg.get("end", 0.0)
        global_start = round(offset_s + raw_start, 2)
        global_end = round(offset_s + raw_end, 2)

        # Map word timestamps if present
        mapped_words = []
        if seg.get("words"):
            for w in seg["words"]:
                mapped_words.append({
                    "word": w.get("word", "").strip(),
                    "start": round(offset_s + w.get("start", 0.0), 2),
                    "end": round(offset_s + w.get("end", 0.0), 2),
                    "probability": round(w.get("probability", 1.0), 3) if w.get("probability") is not None else None
                })

        mapped_segments.append({
            "chunk_index": chunk_meta["chunk_index"],
            "start": global_start,
            "end": max(global_end, global_start),
            "text": text,
            "confidence": round(seg.get("confidence", 0.0), 3) if seg.get("confidence") is not None else None,
            "words": mapped_words if mapped_words else None
        })

    return mapped_segments


def merge_and_format_transcript(
    all_segments: List[Dict[str, Any]],
    paragraph_silence_threshold_s: float = 1.5
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    1. Deduplicates overlapping boundary phrases if chunks were split with overlap.
    2. Builds readable full transcript inserting paragraph breaks when silence > threshold.
    3. Renumbers segments sequentially.

    Returns (full_transcript, final_segments).
    """
    if not all_segments:
        return "", []

    # Sort segments by start time
    sorted_segments = sorted(all_segments, key=lambda s: s["start"])

    # Deduplicate consecutive identical segments
    deduped_segments: List[Dict[str, Any]] = []
    for seg in sorted_segments:
        if deduped_segments:
            prev = deduped_segments[-1]
            # If start time overlaps significantly and text is identical
            if seg["text"].strip().lower() == prev["text"].strip().lower() and abs(seg["start"] - prev["start"]) < 2.0:
                continue
        deduped_segments.append(seg)

    # Build paragraph-structured transcript
    paragraphs: List[str] = []
    current_paragraph_sentences: List[str] = []
    final_segments: List[Dict[str, Any]] = []

    for idx, seg in enumerate(deduped_segments):
        seg_id = idx + 1
        seg_copy = dict(seg)
        seg_copy["segment_id"] = seg_id
        final_segments.append(seg_copy)

        text = seg["text"].strip()
        if not text:
            continue

        if idx > 0:
            prev_seg = deduped_segments[idx - 1]
            silence_gap = seg["start"] - prev_seg["end"]
            if silence_gap >= paragraph_silence_threshold_s:
                if current_paragraph_sentences:
                    paragraphs.append(" ".join(current_paragraph_sentences))
                    current_paragraph_sentences = []

        current_paragraph_sentences.append(text)

    if current_paragraph_sentences:
        paragraphs.append(" ".join(current_paragraph_sentences))

    full_transcript = "\n\n".join(paragraphs).strip()
    return full_transcript, final_segments
