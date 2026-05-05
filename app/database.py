# -*- coding: utf-8 -*-
"""SQLite database layer — initialization and connection management."""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, logger


def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_id     TEXT PRIMARY KEY,
            filename   TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pages (
            doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
            num         INTEGER NOT NULL,
            filename    TEXT NOT NULL,
            ocr_text    TEXT,
            ocr_regions TEXT,
            ocr_time    REAL,
            PRIMARY KEY (doc_id, num)
        );
        CREATE TABLE IF NOT EXISTS dir_cache (
            dir_path       TEXT NOT NULL,
            dir_mtime      REAL NOT NULL,
            ext_filter     TEXT NOT NULL DEFAULT '',
            include_images INTEGER NOT NULL DEFAULT 0,
            blacklist_key  TEXT NOT NULL DEFAULT '',
            files_json     TEXT NOT NULL DEFAULT '[]',
            skipped_count  INTEGER NOT NULL DEFAULT 0,
            scanned_at     TEXT NOT NULL,
            PRIMARY KEY (dir_path, blacklist_key)
        );
    """)
    # Migration: if dir_cache has wrong PK (dir_path only), recreate it
    try:
        pk_cols = [row[1] for row in conn.execute("PRAGMA table_info(dir_cache)").fetchall()
                   if row[5] > 0]  # pk flag > 0
        if len(pk_cols) == 1 and pk_cols[0] == "dir_path":
            logger.info("[DB] Migrating dir_cache to composite PK (dir_path, blacklist_key)...")
            conn.execute("ALTER TABLE dir_cache RENAME TO dir_cache_old")
            conn.execute("""CREATE TABLE dir_cache (
                dir_path       TEXT NOT NULL,
                dir_mtime      REAL NOT NULL,
                ext_filter     TEXT NOT NULL DEFAULT '',
                include_images INTEGER NOT NULL DEFAULT 0,
                blacklist_key  TEXT NOT NULL DEFAULT '',
                files_json     TEXT NOT NULL DEFAULT '[]',
                skipped_count  INTEGER NOT NULL DEFAULT 0,
                scanned_at     TEXT NOT NULL,
                PRIMARY KEY (dir_path, blacklist_key)
            )""")
            conn.execute("""INSERT OR IGNORE INTO dir_cache
                SELECT dir_path, dir_mtime, ext_filter, include_images, blacklist_key,
                       files_json, skipped_count, scanned_at
                FROM dir_cache_old""")
            conn.execute("DROP TABLE dir_cache_old")
    except Exception as e:
        logger.debug(f"[DB] dir_cache migration check: {e}")
    conn.commit()
    conn.close()


@contextmanager
def get_db():
    """Yield a SQLite connection with WAL mode and foreign keys enabled.
    Auto-commits on success, rolls back on exception.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Initialize DB on import
init_db()
logger.info(f"[DB] Initialized: {DB_PATH}")
