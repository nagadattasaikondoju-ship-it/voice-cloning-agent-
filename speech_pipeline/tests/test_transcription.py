import pytest
from app.audio.timestamps import (
    map_chunk_timestamps_to_original,
    merge_and_format_transcript,
    is_hallucinated_segment
)


def test_map_chunk_timestamps_to_original():
    """Verify that chunk local timestamps are properly shifted by chunk start_s offset."""
    chunk_meta = {
        "chunk_index": 3,
        "start_s": 10.5,
        "end_s": 15.0,
        "duration_s": 4.5,
        "is_silent": 0,
        "rms_energy": 0.08
    }

    local_segments = [
        {
            "start": 0.5,
            "end": 2.2,
            "text": "Hello world",
            "confidence": 0.95,
            "words": [
                {"word": "Hello", "start": 0.5, "end": 1.0, "probability": 0.98},
                {"word": "world", "start": 1.1, "end": 2.2, "probability": 0.92}
            ]
        }
    ]

    mapped = map_chunk_timestamps_to_original(chunk_meta, local_segments)
    assert len(mapped) == 1
    seg = mapped[0]
    assert seg["start"] == 11.0  # 10.5 + 0.5
    assert seg["end"] == 12.7    # 10.5 + 2.2
    assert seg["text"] == "Hello world"
    assert len(seg["words"]) == 2
    assert seg["words"][0]["start"] == 11.0
    assert seg["words"][1]["end"] == 12.7


def test_hallucination_filter():
    """Verify known hallucinations on silent/low-energy chunks are detected."""
    assert is_hallucinated_segment("Thank you.", is_chunk_silent=True, rms_energy=0.001) is True
    assert is_hallucinated_segment("Thanks for watching!", is_chunk_silent=True, rms_energy=0.0005) is True
    assert is_hallucinated_segment("", is_chunk_silent=False, rms_energy=0.1) is True
    # Real speech with energy should NOT be filtered
    assert is_hallucinated_segment("The quick brown fox", is_chunk_silent=False, rms_energy=0.05) is False


def test_merge_transcript_paragraph_breaks():
    """Verify paragraph breaks are inserted when silence exceeds 1.5 seconds."""
    segments = [
        {"segment_id": 1, "start": 0.0, "end": 3.0, "text": "First sentence here."},
        # Gap is 2.5s (5.5 - 3.0 > 1.5s)
        {"segment_id": 2, "start": 5.5, "end": 8.0, "text": "Second paragraph starts here."}
    ]

    full_transcript, final_segs = merge_and_format_transcript(segments, paragraph_silence_threshold_s=1.5)
    assert "\n\n" in full_transcript
    assert "First sentence here." in full_transcript
    assert "Second paragraph starts here." in full_transcript
    assert len(final_segs) == 2


def test_merge_transcript_deduplication():
    """Verify adjacent overlapping identical segments are deduplicated."""
    segments = [
        {"segment_id": 1, "start": 0.0, "end": 4.0, "text": "Overlapping boundary text"},
        {"segment_id": 2, "start": 3.8, "end": 6.0, "text": "Overlapping boundary text"},
        {"segment_id": 3, "start": 6.1, "end": 8.0, "text": "Next unique sentence."}
    ]

    full_transcript, final_segs = merge_and_format_transcript(segments)
    assert full_transcript.count("Overlapping boundary text") == 1
    assert len(final_segs) == 2
