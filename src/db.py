"""
Database persistence layer using SQLite.
Tracks post history, duplicate checks, slot tracking, and Drive image usage.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
from src.utils import DATA_DIR, logger

DEFAULT_DB_PATH = DATA_DIR / "autoposter.db"


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """
    Initializes the SQLite database tables if they do not exist.
    """
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    date_str TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    topic TEXT,
                    caption TEXT,
                    image_source TEXT,
                    image_path TEXT,
                    status TEXT NOT NULL,
                    facebook_post_id TEXT,
                    facebook_link TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_posts_date_slot 
                ON posts(date_str, slot, status);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS drive_images (
                    file_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    use_count INTEGER DEFAULT 1
                )
                """
            )
        logger.debug("Database initialized successfully.")
    finally:
        conn.close()


def has_slot_posted_today(
    date_str: str, slot: str, db_path: Optional[Path] = None
) -> bool:
    """
    Checks if a successful post was already published for the given date and slot.
    """
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id FROM posts 
            WHERE date_str = ? AND slot = ? AND status = 'success'
            LIMIT 1
            """,
            (date_str, slot),
        )
        row = cursor.fetchone()
        return row is not None
    finally:
        conn.close()


def get_recent_topics(limit: int = 30, db_path: Optional[Path] = None) -> List[str]:
    """
    Retrieves the last `limit` topics from posts that were successful or dry-run.
    """
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT topic FROM posts 
            WHERE topic IS NOT NULL AND status IN ('success', 'dry_run')
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [r["topic"] for r in rows if r["topic"]]
    finally:
        conn.close()


def get_recent_captions(limit: int = 30, db_path: Optional[Path] = None) -> List[str]:
    """
    Retrieves the last `limit` captions to prevent exact duplicates.
    """
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT caption FROM posts 
            WHERE caption IS NOT NULL AND status IN ('success', 'dry_run')
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [r["caption"] for r in rows if r["caption"]]
    finally:
        conn.close()


def record_post(
    date_str: str,
    slot: str,
    topic: str,
    caption: str,
    image_source: str,
    image_path: Optional[str],
    status: str,
    facebook_post_id: Optional[str] = None,
    facebook_link: Optional[str] = None,
    error: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """
    Inserts a new post record and returns its primary key ID.
    """
    init_db(db_path)
    conn = get_db_connection(db_path)
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO posts (
                    created_at, date_str, slot, topic, caption,
                    image_source, image_path, status,
                    facebook_post_id, facebook_link, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    date_str,
                    slot,
                    topic,
                    caption,
                    image_source,
                    image_path,
                    status,
                    facebook_post_id,
                    facebook_link,
                    error,
                ),
            )
            return cursor.lastrowid
    finally:
        conn.close()


def update_post_status(
    post_id: int,
    status: str,
    facebook_post_id: Optional[str] = None,
    facebook_link: Optional[str] = None,
    error: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """
    Updates status and facebook post metadata for an existing post.
    """
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE posts 
                SET status = ?, facebook_post_id = ?, facebook_link = ?, error = ?
                WHERE id = ?
                """,
                (status, facebook_post_id, facebook_link, error, post_id),
            )
    finally:
        conn.close()


def get_drive_usage_stats(
    file_ids: List[str], db_path: Optional[Path] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Returns use count and last used timestamp for a list of drive file_ids.
    """
    init_db(db_path)
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in file_ids)
        if not placeholders:
            return {}
        cursor.execute(
            f"SELECT file_id, url, last_used_at, use_count FROM drive_images WHERE file_id IN ({placeholders})",
            file_ids,
        )
        rows = cursor.fetchall()
        return {
            r["file_id"]: {
                "url": r["url"],
                "last_used_at": r["last_used_at"],
                "use_count": r["use_count"],
            }
            for r in rows
        }
    finally:
        conn.close()


def record_drive_usage(
    file_id: str, url: str, db_path: Optional[Path] = None
) -> None:
    """
    Updates or inserts a record tracking that a Drive image was used.
    """
    init_db(db_path)
    conn = get_db_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO drive_images (file_id, url, last_used_at, use_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(file_id) DO UPDATE SET
                    url = excluded.url,
                    last_used_at = excluded.last_used_at,
                    use_count = drive_images.use_count + 1
                """,
                (file_id, url, now_iso),
            )
    finally:
        conn.close()
