# ============================================
# database.py — SQLite Database Layer
# Lumina Insights (3-File Architecture)
# ============================================

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "lumina.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables if they do not exist."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Datasets Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                filepath TEXT NOT NULL,
                rows INTEGER,
                cols INTEGER,
                source_type TEXT DEFAULT 'upload',
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safely ensure source_type column exists if table was created previously
        try:
            cursor.execute("ALTER TABLE datasets ADD COLUMN source_type TEXT DEFAULT 'upload'")
        except Exception:
            pass

        # Query History Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                query_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
            )
        """)

        # Insights Cache Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insights_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT,
                title TEXT,
                text TEXT,
                color TEXT,
                icon TEXT,
                FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
            )
        """)
        
        conn.commit()


def save_dataset(dataset_id, filename, filepath, rows, cols, source_type="upload"):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO datasets (id, filename, filepath, rows, cols, source_type) VALUES (?, ?, ?, ?, ?, ?)",
            (dataset_id, filename, filepath, rows, cols, source_type)
        )
        conn.commit()


def get_dataset(dataset_id):
    with get_db() as conn:
        cur = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def add_query_history(dataset_id, question, answer, query_type="general"):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO query_history (dataset_id, question, answer, query_type) VALUES (?, ?, ?, ?)",
            (dataset_id, question, answer, query_type)
        )
        conn.commit()


def get_query_history(dataset_id, limit=10):
    with get_db() as conn:
        cur = conn.execute(
            "SELECT question, answer, query_type, strftime('%H:%M:%S', created_at) as time FROM query_history WHERE dataset_id = ? ORDER BY id DESC LIMIT ?",
            (dataset_id, limit)
        )
        return [dict(row) for row in cur.fetchall()]


def save_insights(dataset_id, insights_list):
    with get_db() as conn:
        conn.execute("DELETE FROM insights_cache WHERE dataset_id = ?", (dataset_id,))
        for ins in insights_list:
            conn.execute(
                "INSERT INTO insights_cache (dataset_id, title, text, color, icon) VALUES (?, ?, ?, ?, ?)",
                (dataset_id, ins.get("title"), ins.get("text"), ins.get("color", "teal"), ins.get("icon", "fas fa-lightbulb"))
            )
        conn.commit()


def get_saved_insights(dataset_id):
    with get_db() as conn:
        cur = conn.execute("SELECT title, text, color, icon FROM insights_cache WHERE dataset_id = ?", (dataset_id,))
        return [dict(row) for row in cur.fetchall()]


if __name__ == "__main__":
    init_db()
    print("[OK] Database initialized successfully at:", DB_PATH)
