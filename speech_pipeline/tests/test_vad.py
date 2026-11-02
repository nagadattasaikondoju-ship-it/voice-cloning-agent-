import numpy as np
import pytest
from app.audio.vad import (
    merge_close_regions,
    split_long_region,
    _energy_based_vad
)


def test_merge_close_regions():
    """Verify that regions separated by less than min_silence_samples are merged."""
    sr = 16000
    # Gap is 0.2s = 3200 samples (less than 400ms = 6400 samples)
    r1 = {"start": 0, "end": 16000}
    r2 = {"start": 19200, "end": 32000}
    min_silence_samples = int(sr * 0.4)

    merged = merge_close_regions([r1, r2], sr, min_silence_samples)
    assert len(merged) == 1
    assert merged[0]["start"] == 0
    assert merged[0]["end"] == 32000


def test_split_long_region_with_overlap():
    """Verify that a 12-second speech block is split into <= 5s chunks with 200ms overlap."""
    sr = 16000
    # 12 seconds of synthetic audio
    audio = np.ones(12 * sr, dtype=np.float32) * 0.1
    chunks = split_long_region(
        start_s=0.0,
        end_s=12.0,
        audio=audio,
        sr=sr,
        max_duration_s=5.0,
        overlap_s=0.2
    )

    # All chunks must be <= 5.0 seconds
    assert len(chunks) >= 3
    for c in chunks:
        assert c["duration_s"] <= 5.001
        assert c["start_s"] < c["end_s"]

    # Check that adjacent chunks have overlap
    for i in range(1, len(chunks)):
        assert chunks[i]["start_s"] < chunks[i - 1]["end_s"]


def test_energy_based_vad_silence_vs_speech():
    """Verify energy-based VAD detects sound burst and ignores silence."""
    sr = 16000
    # 1s silence + 1s tone + 1s silence
    silence = np.zeros(sr, dtype=np.float32)
    t = np.linspace(0, 1, sr, endpoint=False)
    tone = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    audio = np.concatenate([silence, tone, silence])

    regions = _energy_based_vad(audio, sr=sr, threshold=0.05, min_speech_duration_s=0.2)
    assert len(regions) >= 1
    # Detected speech region should start near sample 16000 (1.0s)
    first_region = regions[0]
    assert 14000 <= first_region["start"] <= 18000
