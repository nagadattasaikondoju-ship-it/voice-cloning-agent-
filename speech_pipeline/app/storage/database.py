"""SQLite (WAL mode) persistence for recordings, VAD chunks and transcript segments."""
import json
import sqlite3
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from app.config import settings

logger = logging.getLogger("speech_pipeline.storage.database")

_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    recording_id TEXT PRIMARY KEY,
    filename TEXT,
    raw_audio_path TEXT,
    wav_16k_path TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    duration_seconds REAL,
    language TEXT,
    language_probability REAL,
    full_transcript TEXT,
    vad_metadata_path TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_file_path TEXT NOT NULL,
    start_s REAL,
    end_s REAL,
    duration_s REAL,
    has_overlap INTEGER DEFAULT 0,
    is_silent INTEGER DEFAULT 0,
    rms_energy REAL
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
    segment_id INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    text TEXT NOT NULL,
    confidence REAL,
    words_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_recording ON chunks(recording_id);
CREATE INDEX IF NOT EXISTS idx_segments_recording ON segments(recording_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    settings.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.sqlite_db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _write_lock, get_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    logger.info(f"SQLite database ready at {settings.sqlite_db_path}")


def create_recording(
    recording_id: str,
    filename: str,
    raw_audio_path: str,
    wav_16k_path: str,
    duration_seconds: float,
    language: Optional[str] = None,
) -> None:
    now = _now()
    with _write_lock, get_connection() as conn:
        conn.execute(
            """
            INSERT INTO recordings (recording_id, filename, raw_audio_path, wav_16k_path, status,
                                    duration_seconds, language, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (recording_id, filename, raw_audio_path, wav_16k_path, duration_seconds, language, now, now),
        )


def get_recording(recording_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM recordings WHERE recording_id = ?", (recording_id,)).fetchone()
    return dict(row) if row else None


def update_recording_status(recording_id: str, status: str, error_message: Optional[str] = None) -> None:
    with _write_lock, get_connection() as conn:
        conn.execute(
            "UPDATE recordings SET status = ?, error_message = ?, updated_at = ? WHERE recording_id = ?",
            (status, error_message, _now(), recording_id),
        )


def update_recording_result(
    recording_id: str,
    status: str,
    duration_seconds: float,
    language: str,
    language_probability: float,
    full_transcript: str,
    vad_metadata_path: Optional[str] = None,
) -> None:
    with _write_lock, get_connection() as conn:
        conn.execute(
            """
            UPDATE recordings
            SET status = ?, duration_seconds = ?, language = ?, language_probability = ?,
                full_transcript = ?, vad_metadata_path = ?, error_message = NULL, updated_at = ?
            WHERE recording_id = ?
            """,
            (status, duration_seconds, language, language_probability, full_transcript,
             vad_metadata_path, _now(), recording_id),
        )


def add_chunks(recording_id: str, chunks: List[Dict[str, Any]]) -> None:
    with _write_lock, get_connection() as conn:
        conn.execute("DELETE FROM chunks WHERE recording_id = ?", (recording_id,))
        conn.executemany(
            """
            INSERT INTO chunks (recording_id, chunk_index, chunk_file_path, start_s, end_s,
                                duration_s, has_overlap, is_silent, rms_energy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (recording_id, c["chunk_index"], c["chunk_file_path"], c.get("start_s"), c.get("end_s"),
                 c.get("duration_s"), c.get("has_overlap", 0), c.get("is_silent", 0), c.get("rms_energy"))
                for c in chunks
            ],
        )


def add_segments(recording_id: str, segments: List[Dict[str, Any]]) -> None:
    with _write_lock, get_connection() as conn:
        conn.execute("DELETE FROM segments WHERE recording_id = ?", (recording_id,))
        conn.executemany(
            """
            INSERT INTO segments (recording_id, segment_id, start_time, end_time, text, confidence, words_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (recording_id, s["segment_id"], s["start"], s["end"], s["text"], s.get("confidence"),
                 json.dumps(s["words"]) if s.get("words") else None)
                for s in segments
            ],
        )


def get_recording_segments(recording_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE recording_id = ? ORDER BY segment_id", (recording_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["words"] = json.loads(d.pop("words_json")) if d.get("words_json") else None
        result.append(d)
    return result


def get_recording_chunks(recording_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM chunks WHERE recording_id = ? ORDER BY chunk_index", (recording_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_recording(recording_id: str) -> bool:
    with _write_lock, get_connection() as conn:
        cur = conn.execute("DELETE FROM recordings WHERE recording_id = ?", (recording_id,))
        return cur.rowcount > 0
