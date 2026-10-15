"""Память переводов + глоссарий (SQLite, WAL, потокобезопасно)."""

from __future__ import annotations

import csv
import difflib
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..models.translation import DictionaryEntry

_CHUNK = 400


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DictionaryStore:
    """Persistent translation memory: source_text -> target_text per language pair."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._glossary_cache: Dict[Tuple[str, str], Optional[Tuple[re.Pattern, Dict[str, str]]]] = {}
        self._init_db()

    # -- infrastructure -------------------------------------------------
    def _init_db(self):
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS dictionary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL, source_language TEXT NOT NULL,
                    target_text TEXT NOT NULL, target_language TEXT NOT NULL,
                    handle TEXT DEFAULT '', context TEXT DEFAULT '',
                    usage_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    source_mod TEXT DEFAULT '', verified INTEGER DEFAULT 0,
                    UNIQUE(source_text, source_language, target_language))""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_lookup ON dictionary(source_text, source_language, target_language)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_src_lower ON dictionary(source_text COLLATE NOCASE)")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS glossary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL, translation TEXT NOT NULL,
                    source_language TEXT NOT NULL, target_language TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    UNIQUE(term, source_language, target_language))""")

    def close(self):
        with self._lock:
            self._conn.close()

    # -- exact / fuzzy lookup -------------------------------------------
    def lookup(self, source_text: str, source_lang: str, target_lang: str) -> Optional[DictionaryEntry]:
        """Точное совпадение (затем без учёта регистра и краевых пробелов). +1 к usage_count."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM dictionary WHERE source_text=? AND source_language=? AND target_language=?",
                (source_text, source_lang, target_lang)).fetchone()
            if row is None and source_text.strip():
                row = self._conn.execute(
                    "SELECT * FROM dictionary WHERE source_text=? COLLATE NOCASE "
                    "AND source_language=? AND target_language=? LIMIT 1",
                    (source_text.strip(), source_lang, target_lang)).fetchone()
            if row is None:
                return None
            self._conn.execute("UPDATE dictionary SET usage_count=usage_count+1 WHERE id=?", (row["id"],))
            return self._row_to_entry(row)

    def lookup_many(self, texts: Iterable[str], source_lang: str, target_lang: str,
                    bump: bool = True) -> Dict[str, DictionaryEntry]:
        """Пакетный точный поиск: {source_text: entry}. bump=False — без изменения счётчиков."""
        uniq = list(dict.fromkeys(texts))
        found: Dict[str, DictionaryEntry] = {}
        with self._lock, self._conn:
            for i in range(0, len(uniq), _CHUNK):
                part = uniq[i:i + _CHUNK]
                marks = ",".join("?" * len(part))
                rows = self._conn.execute(
                    f"SELECT * FROM dictionary WHERE source_language=? AND target_language=? "
                    f"AND source_text IN ({marks})", [source_lang, target_lang, *part]).fetchall()
                for r in rows:
                    found[r["source_text"]] = self._row_to_entry(r)
                if bump and rows:
                    self._conn.executemany("UPDATE dictionary SET usage_count=usage_count+1 WHERE id=?",
                                           [(r["id"],) for r in rows])
        return found

    def lookup_fuzzy(self, text: str, source_lang: str, target_lang: str,
                     threshold: float = 0.9) -> Optional[Tuple[DictionaryEntry, float]]:
        """Самое похожее вхождение с похожестью >= threshold (для подсказок, не для авто-подстановки)."""
        n = len(text)
        if n < 8:
            return None
        lo, hi = int(n * 0.75), int(n * 1.34) + 1
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM dictionary WHERE source_language=? AND target_language=? "
                "AND length(source_text) BETWEEN ? AND ? LIMIT 3000",
                (source_lang, target_lang, lo, hi)).fetchall()
        best, best_r = None, 0.0
        sm = difflib.SequenceMatcher(autojunk=False)
        sm.set_seq2(text)
        for r in rows:
            sm.set_seq1(r["source_text"])
            if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
                continue
            ratio = sm.ratio()
            if ratio >= threshold and ratio > best_r:
                best, best_r = r, ratio
        return (self._row_to_entry(best), best_r) if best is not None else None

    # -- write -----------------------------------------------------------
    _UPSERT = """INSERT INTO dictionary
        (source_text, source_language, target_text, target_language, handle, context,
         usage_count, created_at, updated_at, source_mod, verified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_text, source_language, target_language) DO UPDATE SET
            target_text=excluded.target_text, updated_at=excluded.updated_at,
            verified=excluded.verified, handle=excluded.handle, context=excluded.context,
            source_mod=CASE WHEN excluded.source_mod<>'' THEN excluded.source_mod ELSE dictionary.source_mod END
        WHERE dictionary.verified=0 OR excluded.verified=1"""

    @staticmethod
    def _params(e: DictionaryEntry, now: str):
        return (e.source_text, e.source_language, e.target_text, e.target_language,
                e.handle, e.context, e.usage_count, now, now, e.source_mod, int(e.verified))

    def add(self, entry: DictionaryEntry) -> None:
        """Вставка/обновление. Проверенную запись (verified) автоперевод не затирает."""
        self.add_many([entry])

    def add_many(self, entries: List[DictionaryEntry]) -> int:
        now = datetime.now().isoformat()
        with self._lock, self._conn:
            self._conn.executemany(self._UPSERT, [self._params(e, now) for e in entries])
        return len(entries)

    def update_target(self, source_text: str, source_lang: str, target_lang: str,
                      new_target: str, verified: bool = True) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE dictionary SET target_text=?, verified=?, updated_at=? "
                "WHERE source_text=? AND source_language=? AND target_language=?",
                (new_target, int(verified), datetime.now().isoformat(), source_text, source_lang, target_lang))
            return cur.rowcount > 0

    def delete_by_source(self, source_text: str, source_lang: str, target_lang: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM dictionary WHERE source_text=? AND source_language=? AND target_language=?",
                (source_text, source_lang, target_lang))
            return cur.rowcount > 0

    # -- read ------------------------------------------------------------
    def search(self, query: str, target_lang: str = "", limit: int = 500,
               in_target: bool = False, only_verified: bool = False) -> List[DictionaryEntry]:
        like = f"%{_like_escape(query)}%"
        cond = "(source_text LIKE ? ESCAPE '\\'" + (" OR target_text LIKE ? ESCAPE '\\')" if in_target else ")")
        args: list = [like] + ([like] if in_target else [])
        q = f"SELECT * FROM dictionary WHERE {cond}"
        if target_lang:
            q += " AND target_language=?"
            args.append(target_lang)
        if only_verified:
            q += " AND verified=1"
        q += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [self._row_to_entry(r) for r in self._conn.execute(q, args).fetchall()]

    def count(self, source_lang: str = "", target_lang: str = "") -> int:
        q, args = "SELECT COUNT(*) FROM dictionary WHERE 1=1", []
        if source_lang:
            q += " AND source_language=?"
            args.append(source_lang)
        if target_lang:
            q += " AND target_language=?"
            args.append(target_lang)
        with self._lock:
            return self._conn.execute(q, args).fetchone()[0]

    # -- CSV ---------------------------------------------------------------
    CSV_FIELDS = ["source_text", "target_text", "source_language", "target_language", "verified", "usage_count"]

    def export_csv(self, path) -> int:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM dictionary ORDER BY id").fetchall()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r[k] for k in self.CSV_FIELDS})
        return len(rows)

    def import_csv(self, path, default_source: str = "en", default_target: str = "ru",
                   verified: bool = True) -> int:
        entries = []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                src, tgt = (row.get("source_text") or "").strip(), (row.get("target_text") or "").strip()
                if not src or not tgt:
                    continue
                entries.append(DictionaryEntry(
                    source_text=src, target_text=tgt,
                    source_language=(row.get("source_language") or default_source),
                    target_language=(row.get("target_language") or default_target),
                    verified=verified, source_mod="csv"))
        return self.add_many(entries)

    # -- glossary ------------------------------------------------------------
    def glossary_add(self, term: str, translation: str, source_lang: str, target_lang: str, note: str = ""):
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO glossary(term, translation, source_language, target_language, note) "
                "VALUES(?,?,?,?,?) ON CONFLICT(term, source_language, target_language) "
                "DO UPDATE SET translation=excluded.translation, note=excluded.note",
                (term.strip(), translation.strip(), source_lang, target_lang, note))
        self._glossary_cache.clear()

    def glossary_delete(self, term: str, source_lang: str, target_lang: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM glossary WHERE term=? AND source_language=? AND target_language=?",
                (term, source_lang, target_lang))
        self._glossary_cache.clear()
        return cur.rowcount > 0

    def glossary_list(self, source_lang: str = "", target_lang: str = "") -> List[sqlite3.Row]:
        q, args = "SELECT * FROM glossary WHERE 1=1", []
        if source_lang:
            q += " AND source_language=?"
            args.append(source_lang)
        if target_lang:
            q += " AND target_language=?"
            args.append(target_lang)
        with self._lock:
            return self._conn.execute(q + " ORDER BY term COLLATE NOCASE", args).fetchall()

    def glossary_for(self, text: str, source_lang: str, target_lang: str) -> Dict[str, str]:
        """Термины глоссария, встречающиеся в тексте: {term: перевод}."""
        key = (source_lang, target_lang)
        if key not in self._glossary_cache:
            rows = self.glossary_list(source_lang, target_lang)
            if rows:
                terms = {r["term"].lower(): r["translation"] for r in rows if r["term"]}
                alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
                self._glossary_cache[key] = (re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.IGNORECASE), terms)
            else:
                self._glossary_cache[key] = None
        entry = self._glossary_cache[key]
        if not entry:
            return {}
        rx, terms = entry
        found = {}
        for m in rx.finditer(text):
            t = m.group(0).lower()
            found[m.group(0)] = terms[t]
        return found

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> DictionaryEntry:
        return DictionaryEntry(
            source_text=row["source_text"], source_language=row["source_language"],
            target_text=row["target_text"], target_language=row["target_language"],
            handle=row["handle"], context=row["context"], usage_count=row["usage_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_mod=row["source_mod"], verified=bool(row["verified"]))
