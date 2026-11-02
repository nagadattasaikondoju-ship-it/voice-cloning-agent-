import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Tuple
import numpy as np

logger = logging.getLogger("speech_pipeline.preprocess")


class AudioProcessingError(Exception):
    """Raised when audio conversion or normalization fails."""
    pass


def is_ffmpeg_available() -> bool:
    """Checks if ffmpeg is available in system PATH."""
    return shutil.which("ffmpeg") is not None


def get_audio_duration_seconds(file_path: Path) -> float:
    """
    Returns audio duration in seconds using soundfile or wave.
    """
    try:
        import soundfile as sf
        info = sf.info(str(file_path))
        return float(info.duration)
    except Exception:
        pass

    try:
        import wave
        with wave.open(str(file_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return float(frames) / float(rate)
    except Exception as e:
        logger.warning(f"Failed to get audio duration with wave: {e}")
        return 0.0


def normalize_audio_samples(samples: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    """
    Normalizes audio samples array to target peak volume without clipping.
    Samples should be float32 in range [-1.0, 1.0].
    """
    if samples.size == 0:
        return samples
    
    max_val = np.max(np.abs(samples))
    if max_val > 1e-6:
        # Scale to target peak
        scaling_factor = target_peak / max_val
        normalized = samples * scaling_factor
        return np.clip(normalized, -1.0, 1.0)
    return samples


def convert_to_wav_16k_mono(input_path: Path, output_path: Path) -> float:
    """
    Converts any audio format (WAV, MP3, M4A, OGG, WEBM, etc.) to 16,000 Hz,
    1-channel (mono), 16-bit PCM WAV, and normalizes peak volume without clipping.

    Returns the duration in seconds.
    """
    if not input_path.exists():
        raise AudioProcessingError(f"Input audio file not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_wav = output_path.with_name(f"{output_path.stem}_temp.wav")

    # Step 1: Resample to 16kHz mono 16-bit PCM WAV using ffmpeg if available
    converted = False
    if is_ffmpeg_available():
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            "-vn",
            str(temp_wav)
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=120
            )
            converted = True
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode("utf-8", errors="replace")
            logger.warning(f"ffmpeg conversion failed: {err_msg}")
        except Exception as e:
            logger.warning(f"ffmpeg execution error: {e}")

    # Fallback to soundfile / scipy if ffmpeg failed or is unavailable
    if not converted:
        try:
            import soundfile as sf
            from scipy import signal

            data, samplerate = sf.read(str(input_path))
            # Convert multi-channel to mono
            if data.ndim > 1:
                data = np.mean(data, axis=1)

            # Resample to 16000 Hz if needed
            target_sr = 16000
            if samplerate != target_sr:
                num_samples = int(len(data) * target_sr / samplerate)
                data = signal.resample(data, num_samples)

            sf.write(str(temp_wav), data.astype(np.float32), target_sr, subtype="PCM_16")
            converted = True
        except Exception as e:
            if temp_wav.exists():
                temp_wav.unlink(missing_ok=True)
            raise AudioProcessingError(f"Failed to convert audio using both ffmpeg and soundfile: {e}")

    # Step 2: Peak normalize the 16kHz mono audio and save to final output_path
    try:
        import soundfile as sf
        audio_data, sr = sf.read(str(temp_wav), dtype="float32")
        norm_data = normalize_audio_samples(audio_data, target_peak=0.95)
        sf.write(str(output_path), norm_data, sr, subtype="PCM_16")
        
        # Cleanup temp file
        if temp_wav.exists():
            temp_wav.unlink(missing_ok=True)

        duration = float(len(norm_data)) / float(sr)
        logger.info(f"Converted {input_path.name} to 16kHz mono WAV (duration: {duration:.2f}s)")
        return duration
    except Exception as e:
        if temp_wav.exists():
            temp_wav.unlink(missing_ok=True)
        raise AudioProcessingError(f"Failed to normalize audio: {e}")
