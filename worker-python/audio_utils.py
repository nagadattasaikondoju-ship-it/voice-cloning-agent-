"""ffmpeg helpers: browsers record WebM/Opus, providers want MP3/WAV, and we store MP3."""
import json
import subprocess
from pathlib import Path


class AudioConversionError(RuntimeError):
    pass


def _run(cmd: list) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioConversionError(proc.stderr.strip()[-500:] or "ffmpeg failed")


def convert(src: str, dest: str, max_seconds: float = 0.0, mono_16k: bool = False) -> str:
    """Transcode any input ffmpeg understands; output format follows dest's extension."""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src]
    if max_seconds > 0:
        cmd += ["-t", str(max_seconds)]
    if mono_16k:
        cmd += ["-ac", "1", "-ar", "16000"]
    if dest.endswith(".mp3"):
        cmd += ["-codec:a", "libmp3lame", "-b:a", "128k"]
    _run(cmd + [dest])
    return dest


def to_mp3_bytes(src: str) -> bytes:
    dest = str(Path(src).with_suffix(".converted.mp3"))
    convert(src, dest)
    data = Path(dest).read_bytes()
    Path(dest).unlink(missing_ok=True)
    return data


def duration_seconds(path: str) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True,
        text=True,
    )
    try:
        return round(float(json.loads(proc.stdout)["format"]["duration"]), 2)
    except Exception:
        return 0.0
