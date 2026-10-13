"""Translation memory / dictionary backed by SQLite."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models.translation import DictionaryEntry


class DictionaryStore:
    """Persistent translation memory: source_text -> target_text per language pair."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _close(conn: sqlite3.Connection):
        try:
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dictionary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_text TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    handle TEXT DEFAULT '',
                    context TEXT DEFAULT '',
                    usage_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_mod TEXT DEFAULT '',
                    verified INTEGER DEFAULT 0,
                    UNIQUE(source_text, source_language, target_language)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lookup
                ON dictionary(source_text, source_language, target_language)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_src_lower
                ON dictionary(source_text COLLATE NOCASE)
            """)
        finally:
            self._close(conn)

    def lookup(self, source_text: str, source_lang: str, target_lang: str) -> Optional[DictionaryEntry]:
        """Exact-match lookup. Increments usage_count on hit."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM dictionary WHERE source_text = ? AND source_language = ? AND target_language = ?",
                (source_text, source_lang, target_lang),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE dictionary SET usage_count = usage_count + 1 WHERE id = ?", (row["id"],)
            )
            return self._row_to_entry(row)
        finally:
            self._close(conn)

    def add(self, entry: DictionaryEntry) -> None:
        """Insert or update a dictionary entry."""
        now = datetime.now().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO dictionary
                   (source_text, source_language, target_text, target_language,
                    handle, context, usage_count, created_at, updated_at, source_mod, verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_text, source_language, target_language)
                   DO UPDATE SET target_text = excluded.target_text,
                                 updated_at = excluded.updated_at,
                                 usage_count = dictionary.usage_count + 1""",
                (
                    entry.source_text, entry.source_language,
                    entry.target_text, entry.target_language,
                    entry.handle, entry.context, entry.usage_count,
                    now, now, entry.source_mod, int(entry.verified),
                ),
            )
        finally:
            self._close(conn)

    def add_many(self, entries: List[DictionaryEntry]) -> int:
        for e in entries:
            self.add(e)
        return len(entries)

    def search(self, query: str, target_lang: str, limit: int = 500) -> List[DictionaryEntry]:
        conn = self._connect()
        try:
            q = "SELECT * FROM dictionary WHERE source_text LIKE ?"
            args: list = [f"%{query}%"]
            if target_lang:
                q += " AND target_language = ?"
                args.append(target_lang)
            q += " ORDER BY updated_at DESC LIMIT ?"
            args.append(limit)
            rows = conn.execute(q, args).fetchall()
            return [self._row_to_entry(r) for r in rows]
        finally:
            self._close(conn)

    def count(self, source_lang: str = "", target_lang: str = "") -> int:
        conn = self._connect()
        try:
            q = "SELECT COUNT(*) FROM dictionary WHERE 1=1"
            args: list = []
            if source_lang:
                q += " AND source_language = ?"
                args.append(source_lang)
            if target_lang:
                q += " AND target_language = ?"
                args.append(target_lang)
            return conn.execute(q, args).fetchone()[0]
        finally:
            self._close(conn)

    def delete_by_source(self, source_text: str, source_lang: str, target_lang: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM dictionary WHERE source_text = ? AND source_language = ? AND target_language = ?",
                (source_text, source_lang, target_lang),
            )
            return cur.rowcount > 0
        finally:
            self._close(conn)

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> DictionaryEntry:
        return DictionaryEntry(
            source_text=row["source_text"],
            source_language=row["source_language"],
            target_text=row["target_text"],
            target_language=row["target_language"],
            handle=row["handle"],
            context=row["context"],
            usage_count=row["usage_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_mod=row["source_mod"],
            verified=bool(row["verified"]),
        )