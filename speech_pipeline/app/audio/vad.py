import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import soundfile as sf

from app.config import settings
from app.storage.files import get_chunk_path, get_vad_metadata_path, save_json

logger = logging.getLogger("speech_pipeline.vad")


class SileroVADSingleton:
    """
    Singleton holder for the Silero VAD model to ensure it is only loaded once.
    """
    _instance: Optional["SileroVADSingleton"] = None
    _model = None
    _utils = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SileroVADSingleton, cls).__new__(cls)
            cls._instance._load_model()
        return cls._instance

    def _load_model(self):
        """Loads Silero VAD model via silero_vad package or torch hub."""
        logger.info("Initializing Silero VAD model singleton...")
        try:
            from silero_vad import load_silero_vad
            self._model = load_silero_vad(onnx=False)
            logger.info("Silero VAD model loaded successfully via silero_vad package.")
            return
        except Exception as e:
            logger.warning(f"Could not load via silero_vad package ({e}), falling back to torch.hub...")

        try:
            import torch
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True
            )
            self._model = model
            self._utils = utils
            logger.info("Silero VAD model loaded successfully via torch.hub.")
            return
        except Exception as e:
            logger.warning(f"Silero VAD loading fallback engaged (energy-based fallback available if torch fails): {e}")
            self._model = None

    @property
    def model(self):
        return self._model


def get_vad_model():
    """Returns the singleton VAD model."""
    singleton = SileroVADSingleton()
    return singleton.model


def _energy_based_vad(
    audio: np.ndarray,
    sr: int = 16000,
    threshold: float = 0.015,
    min_speech_duration_s: float = 0.2,
    min_silence_duration_s: float = 0.4
) -> List[Dict[str, int]]:
    """
    Robust fallback VAD based on short-time RMS energy when torch/Silero weights are offline.
    """
    frame_len = int(sr * 0.03)  # 30ms frames
    hop_len = int(sr * 0.01)    # 10ms hop
    num_frames = (len(audio) - frame_len) // hop_len + 1

    if num_frames <= 0:
        return []

    energies = []
    for i in range(num_frames):
        start = i * hop_len
        frame = audio[start : start + frame_len]
        rms = np.sqrt(np.mean(frame**2))
        energies.append(rms)

    speech_flags = [e > threshold for e in energies]

    # Convert frame flags to sample ranges
    regions = []
    in_speech = False
    start_frame = 0

    for i, flag in enumerate(speech_flags):
        if flag and not in_speech:
            in_speech = True
            start_frame = i
        elif not flag and in_speech:
            in_speech = False
            start_sample = start_frame * hop_len
            end_sample = min(len(audio), i * hop_len + frame_len)
            duration_s = (end_sample - start_sample) / sr
            if duration_s >= min_speech_duration_s:
                regions.append({"start": start_sample, "end": end_sample})

    if in_speech:
        start_sample = start_frame * hop_len
        end_sample = len(audio)
        if (end_sample - start_sample) / sr >= min_speech_duration_s:
            regions.append({"start": start_sample, "end": end_sample})

    return regions


def detect_speech_regions(
    audio: np.ndarray,
    sr: int = 16000
) -> List[Dict[str, int]]:
    """
    Runs Silero VAD on full audio. Returns list of sample dicts:
    [{'start': int, 'end': int}, ...]
    """
    model = get_vad_model()
    if model is not None:
        try:
            import torch
            tensor_audio = torch.from_numpy(audio).float()
            
            # Use silero_vad package function if available
            try:
                from silero_vad import get_speech_timestamps
                timestamps = get_speech_timestamps(
                    tensor_audio,
                    model,
                    threshold=settings.vad_threshold,
                    sampling_rate=sr,
                    min_speech_duration_ms=settings.vad_min_speech_duration_ms,
                    max_speech_duration_s=float("inf"), # we handle chunking separately
                    min_silence_duration_ms=settings.vad_min_silence_duration_ms,
                    speech_pad_ms=settings.vad_speech_pad_ms
                )
                return timestamps
            except Exception as e:
                logger.warning(f"Error using silero_vad.get_speech_timestamps: {e}")

            # Fallback to torch hub get_speech_timestamps
            try:
                hub_get_timestamps = SileroVADSingleton()._utils[0] if SileroVADSingleton()._utils else None
                if hub_get_timestamps:
                    timestamps = hub_get_timestamps(
                        tensor_audio,
                        model,
                        threshold=settings.vad_threshold,
                        sampling_rate=sr,
                        min_speech_duration_ms=settings.vad_min_speech_duration_ms,
                        min_silence_duration_ms=settings.vad_min_silence_duration_ms,
                        speech_pad_ms=settings.vad_speech_pad_ms
                    )
                    return timestamps
            except Exception as e:
                logger.warning(f"Error using torch.hub get_speech_timestamps: {e}")

        except Exception as e:
            logger.warning(f"Silero VAD execution failed: {e}. Using energy-based fallback.")

    # Fallback to energy-based VAD
    return _energy_based_vad(
        audio,
        sr=sr,
        min_speech_duration_s=settings.vad_min_speech_duration_ms / 1000.0,
        min_silence_duration_s=settings.vad_min_silence_duration_ms / 1000.0
    )


def merge_close_regions(
    regions: List[Dict[str, int]],
    sr: int,
    min_silence_samples: int
) -> List[Dict[str, int]]:
    """
    Merges speech regions separated by less than min_silence_duration_ms.
    """
    if not regions:
        return []

    merged = [dict(regions[0])]
    for curr in regions[1:]:
        prev = merged[-1]
        gap = curr["start"] - prev["end"]
        if gap < min_silence_samples:
            # Merge into prev
            prev["end"] = max(prev["end"], curr["end"])
        else:
            merged.append(dict(curr))
    return merged


def split_long_region(
    start_s: float,
    end_s: float,
    audio: np.ndarray,
    sr: int,
    max_duration_s: float = 5.0,
    overlap_s: float = 0.2
) -> List[Dict[str, Any]]:
    """
    Splits any speech region longer than max_duration_s.
    If no natural silence dip exists, splits at 5 seconds with overlap_s (200ms).
    """
    region_dur = end_s - start_s
    if region_dur <= max_duration_s:
        return [{
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": region_dur,
            "has_overlap": False
        }]

    chunks = []
    curr_start = start_s

    while curr_start < end_s:
        potential_end = min(end_s, curr_start + max_duration_s)
        dur = potential_end - curr_start

        if dur <= max_duration_s:
            chunks.append({
                "start_s": curr_start,
                "end_s": potential_end,
                "duration_s": dur,
                "has_overlap": (len(chunks) > 0)
            })
            break

        # Attempt to find a natural dip in audio energy in the window [curr_start + 3.5, curr_start + 5.0]
        window_start_sample = int((curr_start + max_duration_s * 0.7) * sr)
        window_end_sample = int(potential_end * sr)
        best_split_s = potential_end

        if window_end_sample > window_start_sample and window_end_sample <= len(audio):
            sub_window = audio[window_start_sample:window_end_sample]
            step = int(sr * 0.05) # 50ms frames
            min_energy = float("inf")
            min_idx = -1

            for idx in range(0, len(sub_window) - step, step):
                frame_energy = np.mean(sub_window[idx : idx + step] ** 2)
                if frame_energy < min_energy:
                    min_energy = frame_energy
                    min_idx = idx

            if min_idx != -1 and min_energy < 0.005: # found clear energy drop
                best_split_s = (window_start_sample + min_idx + step // 2) / sr

        chunk_dur = best_split_s - curr_start
        has_overlap = False
        chunks.append({
            "start_s": curr_start,
            "end_s": best_split_s,
            "duration_s": chunk_dur,
            "has_overlap": has_overlap
        })

        # Advance curr_start: if split cleanly at natural dip, advance without overlap;
        # otherwise retain 200ms overlap
        if best_split_s == potential_end:
            curr_start = max(curr_start + 1.0, best_split_s - overlap_s)
        else:
            curr_start = best_split_s

    return chunks


def process_vad_and_create_chunks(
    audio_path: Path,
    recording_id: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    1. Loads full 16kHz audio.
    2. Runs Silero VAD on complete audio.
    3. Merges regions separated by less than min_silence_duration_ms.
    4. Applies padding (speech_pad_ms).
    5. Splits regions longer than 5s at natural silence boundaries or with 200ms overlap.
    6. Saves chunk WAV files (chunk_001.wav, chunk_002.wav, etc.).
    7. Saves vad_regions.json.

    Returns (chunks_metadata, vad_metadata).
    """
    audio, sr = sf.read(str(audio_path), dtype="float32")
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    total_samples = len(audio)
    total_dur_s = float(total_samples) / float(sr)

    # 1. Detect speech regions
    raw_regions = detect_speech_regions(audio, sr=sr)
    logger.info(f"VAD detected {len(raw_regions)} initial speech regions for {recording_id}")

    # 2. Merge close speech regions
    min_silence_samples = int(sr * (settings.vad_min_silence_duration_ms / 1000.0))
    merged_regions = merge_close_regions(raw_regions, sr, min_silence_samples)

    # 3. Add speech padding (speech_pad_ms: 200ms)
    pad_samples = int(sr * (settings.vad_speech_pad_ms / 1000.0))
    padded_regions = []
    for r in merged_regions:
        p_start = max(0, r["start"] - pad_samples)
        p_end = min(total_samples, r["end"] + pad_samples)
        padded_regions.append({"start": p_start, "end": p_end})

    # Re-merge after padding if overlaps were created
    final_speech_regions = merge_close_regions(padded_regions, sr, min_silence_samples=0)

    # 4. Handle cases with no detected speech (silent or low-noise audio)
    if not final_speech_regions:
        logger.warning(f"No speech detected for {recording_id}. Creating fallback chunk.")
        final_speech_regions = [{
            "start": 0,
            "end": min(total_samples, int(sr * settings.vad_max_speech_duration_s))
        }]
        is_audio_silent = True
    else:
        is_audio_silent = False

    # 5. Split long regions into <= 5s chunks
    chunks_meta = []
    chunk_index = 1
    total_speech_samples = 0

    for region in final_speech_regions:
        start_s = region["start"] / sr
        end_s = region["end"] / sr
        total_speech_samples += (region["end"] - region["start"])

        split_chunks = split_long_region(
            start_s=start_s,
            end_s=end_s,
            audio=audio,
            sr=sr,
            max_duration_s=settings.vad_max_speech_duration_s,
            overlap_s=settings.vad_overlap_ms / 1000.0
        )

        for sc in split_chunks:
            chunk_file_path = get_chunk_path(recording_id, chunk_index)
            c_start_sample = int(sc["start_s"] * sr)
            c_end_sample = min(total_samples, int(sc["end_s"] * sr))
            chunk_audio = audio[c_start_sample:c_end_sample]

            # Write chunk WAV (16kHz, mono, PCM_16)
            sf.write(str(chunk_file_path), chunk_audio, sr, subtype="PCM_16")

            # Check chunk RMS energy
            chunk_rms = float(np.sqrt(np.mean(chunk_audio**2))) if len(chunk_audio) > 0 else 0.0

            chunks_meta.append({
                "chunk_index": chunk_index,
                "chunk_file_path": str(chunk_file_path),
                "start_s": round(sc["start_s"], 3),
                "end_s": round(sc["end_s"], 3),
                "duration_s": round(sc["end_s"] - sc["start_s"], 3),
                "has_overlap": 1 if sc["has_overlap"] else 0,
                "is_silent": 1 if (is_audio_silent or chunk_rms < 0.003) else 0,
                "rms_energy": chunk_rms
            })
            chunk_index += 1

    # 6. Build and save VAD metadata
    speech_duration_s = total_speech_samples / sr
    vad_metadata = {
        "sample_rate": sr,
        "total_audio_duration_s": round(total_dur_s, 3),
        "speech_duration_s": round(speech_duration_s, 3),
        "speech_percentage": round((speech_duration_s / max(total_dur_s, 0.001)) * 100.0, 2),
        "total_chunks": len(chunks_meta),
        "regions": [
            {
                "region_id": idx + 1,
                "start_s": round(r["start"] / sr, 3),
                "end_s": round(r["end"] / sr, 3),
                "duration_s": round((r["end"] - r["start"]) / sr, 3),
                "sample_start": r["start"],
                "sample_end": r["end"]
            }
            for idx, r in enumerate(final_speech_regions)
        ]
    }

    vad_json_path = get_vad_metadata_path(recording_id)
    save_json(vad_json_path, vad_metadata)
    logger.info(f"Saved {len(chunks_meta)} speech chunks and VAD metadata for {recording_id}")

    return chunks_meta, vad_metadata
