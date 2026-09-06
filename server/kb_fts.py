"""SQLite FTS5 index for knowledge-base chunks (hybrid retrieval)."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple


_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百千零〇\d]+条")

# Schema v3: title UNINDEXED column so FTS-only hits can return title.
# (v2 prepended title into body_idx only; search could not surface title.)
FTS_SCHEMA_VERSION = 3

_FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5(
  chunk_id UNINDEXED,
  document_id UNINDEXED,
  doc_type UNINDEXED,
  title UNINDEXED,
  body UNINDEXED,
  body_idx,
  tokenize = 'unicode61'
)
"""


def prepare_body_for_fts(body: str) -> str:
    """Insert spaces around 「第X条」 so unicode61 indexes them as tokens."""
    text = body or ""
    text = _ARTICLE_RE.sub(r" \g<0> ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_fts_query(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return ""
    articles = _ARTICLE_RE.findall(text)
    # Strip quotes/operators that break MATCH
    cleaned = re.sub(r'["\'*():^]', " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens: List[str] = []
    for a in articles:
        if a not in tokens:
            tokens.append(a)
    # Drop article spans so surrounding CJK still yields separate tokens
    cleaned_wo_articles = _ARTICLE_RE.sub(" ", cleaned)
    cleaned_wo_articles = re.sub(r"\s+", " ", cleaned_wo_articles).strip()
    for part in re.findall(
        r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9\-]+", cleaned_wo_articles
    ):
        if part not in tokens:
            tokens.append(part)
    if not tokens:
        return ""
    # Phrase-ish: quote multi-char tokens for FTS5
    return " OR ".join('"' + t.replace('"', "") + '"' for t in tokens[:12])


def rrf_fuse(
    rank_lists: Sequence[Sequence[str]], *, rrf_k: int = 60
) -> List[Tuple[str, float]]:
    scores: Dict[str, float] = {}
    for ranking in rank_lists:
        for rank, item_id in enumerate(ranking, start=1):
            if not item_id:
                continue
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


class KbFtsIndex:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _table_exists(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("kb_chunks_fts",),
        ).fetchone()
        return row is not None

    def _fts_has_title_column(self, conn: sqlite3.Connection) -> bool:
        if not self._table_exists(conn):
            return False
        try:
            conn.execute("SELECT title FROM kb_chunks_fts LIMIT 0")
            return True
        except sqlite3.Error:
            return False

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kb_fts_meta (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                )
                """
            )
            row = conn.execute(
                "SELECT value FROM kb_fts_meta WHERE key = ?", ("version",)
            ).fetchone()
            version = 0
            if row:
                try:
                    version = int(row["value"])
                except (TypeError, ValueError):
                    version = 0

            # FTS5 cannot ADD COLUMN; recreate when schema is stale / missing title.
            needs_migrate = self._table_exists(conn) and (
                version < FTS_SCHEMA_VERSION or not self._fts_has_title_column(conn)
            )
            if needs_migrate:
                conn.execute("DROP TABLE IF EXISTS kb_chunks_fts")

            conn.execute(_FTS_CREATE_SQL)

            # Brand-new empty index: stamp current schema version.
            # Migrated / legacy non-empty indexes keep stale version so attach_fts rebuilds.
            row = conn.execute(
                "SELECT value FROM kb_fts_meta WHERE key = ?", ("version",)
            ).fetchone()
            if row is None:
                count_row = conn.execute(
                    "SELECT COUNT(*) AS c FROM kb_chunks_fts"
                ).fetchone()
                if int(count_row["c"] if count_row else 0) == 0:
                    conn.execute(
                        "INSERT INTO kb_fts_meta(key, value) VALUES (?, ?)",
                        ("version", str(FTS_SCHEMA_VERSION)),
                    )

    def get_schema_version(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM kb_fts_meta WHERE key = ?", ("version",)
            ).fetchone()
            if not row:
                return 0
            try:
                return int(row["value"])
            except (TypeError, ValueError):
                return 0

    def set_schema_version(self, version: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO kb_fts_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("version", str(int(version))),
            )

    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        if not chunks:
            return
        with self._conn() as conn:
            for ch in chunks:
                cid = ch["chunk_id"]
                raw_body = ch.get("body") or ""
                title = (ch.get("title") or "").strip()
                indexed = (title + " " + raw_body).strip() if title else raw_body
                conn.execute(
                    "DELETE FROM kb_chunks_fts WHERE chunk_id = ?", (cid,)
                )
                conn.execute(
                    """
                    INSERT INTO kb_chunks_fts(
                      chunk_id, document_id, doc_type, title, body, body_idx
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        ch["document_id"],
                        ch["doc_type"],
                        title,
                        raw_body,
                        prepare_body_for_fts(indexed),
                    ),
                )

    def delete_by_document_id(self, document_id: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM kb_chunks_fts WHERE document_id = ?",
                (document_id,),
            )
            return int(cur.rowcount or 0)

    def count(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM kb_chunks_fts"
            ).fetchone()
            return int(row["c"] if row else 0)

    def clear(self) -> None:
        """Delete all rows from the FTS index."""
        with self._conn() as conn:
            conn.execute("DELETE FROM kb_chunks_fts")

    def search(
        self,
        query: str,
        *,
        doc_type: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        from kb_query_parse import (
            build_fts_match,
            doc_has_article,
            extract_articles,
            extract_law_name_hint,
        )

        match = build_fts_match(query)
        if not match:
            return []
        limit = max(1, min(int(limit), 50))
        filters = ""
        params: List[Any] = [match]
        if doc_type:
            filters += " AND doc_type = ?"
            params.append(doc_type)
        if document_id:
            filters += " AND document_id = ?"
            params.append(document_id)
        hint = extract_law_name_hint(query)
        articles = extract_articles(query)
        fetch_n = limit
        if hint and articles:
            fetch_n = max(limit, min(50, limit * 5))
        params_limit = list(params) + [fetch_n]

        # body_idx is the only indexed text column; MATCH uses it implicitly.
        sql_bm25 = (
            "SELECT chunk_id, document_id, doc_type, title, body, "
            "bm25(kb_chunks_fts) AS rank_score "
            "FROM kb_chunks_fts WHERE kb_chunks_fts MATCH ?"
            + filters
            + " ORDER BY rank_score LIMIT ?"
        )
        sql_rank = (
            "SELECT chunk_id, document_id, doc_type, title, body "
            "FROM kb_chunks_fts WHERE kb_chunks_fts MATCH ?"
            + filters
            + " ORDER BY rank LIMIT ?"
        )
        try:
            with self._conn() as conn:
                try:
                    rows = conn.execute(sql_bm25, params_limit).fetchall()
                except sqlite3.Error:
                    rows = conn.execute(sql_rank, params_limit).fetchall()
        except sqlite3.Error as exc:
            print(f"[KbFtsIndex] search failed: {exc}")
            return []
        out = []
        for i, row in enumerate(rows, start=1):
            out.append(
                {
                    "chunk_id": row["chunk_id"],
                    "document_id": row["document_id"],
                    "doc_type": row["doc_type"],
                    "title": (row["title"] or "") if "title" in row.keys() else "",
                    "body": row["body"],
                    "fts_rank": i,
                }
            )

        if hint and out:
            def _title_ok(title: str) -> bool:
                t = (title or "").strip()
                h = (hint or "").strip()
                if not t or not h:
                    return False
                if h in t or t in h:
                    return True
                for suffix in ("条例", "规定", "办法", "法"):
                    if h.endswith(suffix) and len(h) > len(suffix):
                        stem = h[: -len(suffix)]
                        if stem and stem in t:
                            return True
                return False

            titled = [h for h in out if _title_ok(h.get("title") or "")]
            pool = titled if titled else out
            if articles:
                art_hit = [
                    h
                    for h in pool
                    if any(doc_has_article(h.get("body") or "", a) for a in articles)
                ]
                if art_hit:
                    rest = [h for h in pool if h not in art_hit]
                    pool = art_hit + rest
            for i, h in enumerate(pool[:limit], start=1):
                h["fts_rank"] = i
            return pool[:limit]
        return out[:limit]
