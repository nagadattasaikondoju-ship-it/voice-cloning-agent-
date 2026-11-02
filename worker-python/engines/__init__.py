"""
Voice engines. Each engine module exposes:

    clone(sample_path, voice_id, display_name) -> dict   # fields to store on voice_clones
    synthesize(job, clone_row) -> bytes                  # audio (any format ffmpeg reads)
    delete(voice_id, provider_voice_id) -> None
"""
from engines import elevenlabs, f5, minimax

ENGINES = {"minimax": minimax, "elevenlabs": elevenlabs, "f5": f5}


def get_engine(name: str):
    try:
        return ENGINES[name]
    except KeyError:
        raise ValueError(f"Unknown voice engine '{name}'")
