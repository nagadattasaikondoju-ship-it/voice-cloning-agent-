"""Private local storage shared with the Rust API. Keys look like 'samples/<id>.webm'."""
from pathlib import Path

from settings import STORAGE_DIR

for sub in ("samples", "references", "generated"):
    (STORAGE_DIR / sub).mkdir(parents=True, exist_ok=True)


def path_for(storage_key: str) -> Path:
    path = (STORAGE_DIR / storage_key).resolve()
    if STORAGE_DIR not in path.parents:
        raise ValueError(f"Storage key escapes storage dir: {storage_key!r}")
    return path
