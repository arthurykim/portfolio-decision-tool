"""SQLite persistence: users, watchlists, editable site content."""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "db" / "app.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watchlist (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, symbol)
);
CREATE TABLE IF NOT EXISTS site_content (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

DEFAULT_ABOUT = """# About this site

Built and maintained by Arthur Kim. This is an educational project: track major
index funds and stocks, backtest allocations against decades of real market
data, and learn the concepts along the way.

Nothing here is investment advice. Sign in as the site admin to edit this page.
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO site_content (key, value) VALUES ('about', ?)",
            (DEFAULT_ABOUT,),
        )


# ---------------------------------------------------------------- users
def create_user(username: str, password_hash: str) -> dict:
    with connect() as conn:
        first = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, password_hash, int(first)),
        )
        return {"id": cur.lastrowid, "username": username, "is_admin": first}


def get_user_by_name(username: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# ---------------------------------------------------------------- watchlist
def get_watchlist(user_id: int) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE user_id = ? ORDER BY rowid",
            (user_id,),
        ).fetchall()
        return [r["symbol"] for r in rows]


def add_to_watchlist(user_id: int, symbol: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, symbol) VALUES (?, ?)",
            (user_id, symbol),
        )


def remove_from_watchlist(user_id: int, symbol: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        )


# ---------------------------------------------------------------- content
def get_content(key: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM site_content WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_content(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO site_content (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value),
        )
