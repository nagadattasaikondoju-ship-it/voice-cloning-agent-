"""ffmpeg helpers. Every reference clip and every output goes through the same steps,
so all voices and all generated clips have the same format and loudness."""
import json
import subprocess
from pathlib import Path

REFERENCE_MAX_SECONDS = 20  # Chatterbox conditions on the first ~10-15 s
MIN_SPEECH_SECONDS = 6.0  # Chatterbox requires > 5 s of reference audio


class AudioError(RuntimeError):
    pass


def _ffmpeg(args: list) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(proc.stderr.strip()[-400:] or "ffmpeg failed")


def duration_seconds(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return round(float(json.loads(proc.stdout)["format"]["duration"]), 2)
    except Exception:
        return 0.0


def prepare_reference(src: Path, dest: Path) -> float:
    """Any upload (webm/mp3/m4a/wav/ogg) -> mono 24 kHz WAV, silence trimmed at both ends,
    capped at REFERENCE_MAX_SECONDS. Returns the resulting duration."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2"
    _ffmpeg([
        "-i", str(src),
        "-af", f"{trim},areverse,{trim},areverse",
        "-ac", "1", "-ar", "24000", "-t", str(REFERENCE_MAX_SECONDS),
        str(dest),
    ])
    seconds = duration_seconds(dest)
    if seconds < MIN_SPEECH_SECONDS:
        raise AudioError(
            f"Only {seconds:.1f} s of speech was found in the sample; at least {MIN_SPEECH_SECONDS:.0f} s is needed. "
            "Record 10–30 s of clear speech."
        )
    return seconds


def finalize(src_wav: Path, dest_mp3: Path, speed: float, volume: float) -> float:
    """Model WAV -> MP3 with speed change (pitch preserved), consistent loudness, then volume."""
    speed = min(max(speed, 0.5), 2.0)
    volume = min(max(volume, 0.1), 2.0)
    filters = [f"atempo={speed:.3f}", "loudnorm=I=-16:TP=-1.5:LRA=11", f"volume={volume:.3f}"]
    _ffmpeg([
        "-i", str(src_wav),
        "-af", ",".join(filters),
        "-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "128k",
        str(dest_mp3),
    ])
    return duration_seconds(dest_mp3)
