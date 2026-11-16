"""Audio storage shared with the Rust API: the `blobs` table in Postgres.
Keys look like 'consents/<id>_1.webm', 'references/<voice>.wav', 'generated/<job>.mp3'."""
from pathlib import Path
from typing import Optional

import psycopg2

from settings import DATABASE_URL


def load(key: str) -> Optional[bytes]:
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT data FROM blobs WHERE key = %s", (key,))
        row = cur.fetchone()
        return bytes(row[0]) if row else None


def load_to(key: str, dest: Path) -> bool:
    data = load(key)
    if data is None:
        return False
    dest.write_bytes(data)
    return True


def save(key: str, user_id: str, mime_type: str, data: bytes) -> None:
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO blobs (key, user_id, mime_type, data) VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, mime_type = EXCLUDED.mime_type
            """,
            (key, user_id, mime_type, psycopg2.Binary(data)),
        )


def delete(*keys: str) -> None:
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM blobs WHERE key = ANY(%s)", (list(keys),))
