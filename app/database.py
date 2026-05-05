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
    """)
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
