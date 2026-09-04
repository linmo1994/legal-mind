"""SQLite persistence for knowledge-base documents."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

DOC_TYPES = ("law", "case")
STATUSES = (
    "processing",
    "ready",
    "meta_failed",
    "vector_failed",
    "extract_failed",
    "deleted",
)


class KbStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
            CREATE TABLE IF NOT EXISTS kb_documents (
              id TEXT PRIMARY KEY,
              doc_type TEXT NOT NULL,
              file_id TEXT,
              title TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              meta_json TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              created_by TEXT
            )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kb_doc_type_status "
                "ON kb_documents(doc_type, status)"
            )

    def _row_to_dict(self, row) -> Dict[str, Any]:
        d = dict(row)
        d["meta"] = json.loads(d.pop("meta_json") or "{}")
        return d

    def _validate_doc_type(self, doc_type: str) -> None:
        if doc_type not in DOC_TYPES:
            raise ValueError(f"invalid doc_type: {doc_type}")

    def _validate_status(self, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"invalid status: {status}")

    def create_document(
        self,
        *,
        id: str,
        doc_type: str,
        file_id: str | None,
        title: str,
        status: str,
        meta: dict,
        created_by: str | None,
    ) -> dict:
        self._validate_doc_type(doc_type)
        self._validate_status(status)
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO kb_documents
                  (id, doc_type, file_id, title, status, meta_json,
                   created_at, updated_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    doc_type,
                    file_id,
                    title,
                    status,
                    json.dumps(meta or {}),
                    now,
                    now,
                    created_by,
                ),
            )
        row = self.get_document(id, include_deleted=True)
        assert row is not None
        return row

    def get_document(
        self, id: str, *, include_deleted: bool = False
    ) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM kb_documents WHERE id = ?", (id,)
            ).fetchone()
        if row is None:
            return None
        if not include_deleted and row["status"] == "deleted":
            return None
        return self._row_to_dict(row)

    def list_documents(
        self, *, doc_type: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM kb_documents
                WHERE doc_type = ? AND status != 'deleted'
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (doc_type, limit, offset),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count_documents(self, *, doc_type: str | None = None) -> int:
        with self._conn() as conn:
            if doc_type is None:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM kb_documents WHERE status != 'deleted'"
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM kb_documents
                    WHERE doc_type = ? AND status != 'deleted'
                    """,
                    (doc_type,),
                ).fetchone()
        return int(row["c"])

    def update_document(
        self,
        id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        meta: dict | None = None,
    ) -> dict | None:
        existing = self.get_document(id, include_deleted=True)
        if existing is None:
            return None
        if status is not None:
            self._validate_status(status)
        fields: List[str] = []
        values: List[Any] = []
        if title is not None:
            fields.append("title = ?")
            values.append(title)
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if meta is not None:
            fields.append("meta_json = ?")
            values.append(json.dumps(meta))
        if not fields:
            return existing
        fields.append("updated_at = ?")
        values.append(time.time())
        values.append(id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE kb_documents SET {', '.join(fields)} WHERE id = ?",
                values,
            )
        return self.get_document(id, include_deleted=True)

    def soft_delete(self, id: str) -> bool:
        existing = self.get_document(id, include_deleted=True)
        if existing is None or existing["status"] == "deleted":
            return False
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE kb_documents
                SET status = 'deleted', updated_at = ?
                WHERE id = ?
                """,
                (time.time(), id),
            )
        return True
