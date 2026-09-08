"""SQLite persistence for document artifacts, approval tasks, and audit events."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

ARTIFACT_STATUS_DRAFT = "draft"
ARTIFACT_STATUS_PENDING_LEAD = "pending_lead"
ARTIFACT_STATUS_PENDING_PARTNER = "pending_partner"
ARTIFACT_STATUS_APPROVED = "approved"

TASK_STEP_LEAD = "lead"
TASK_STEP_PARTNER = "partner"

TASK_STATUS_OPEN = "open"
TASK_STATUS_DONE = "done"
TASK_STATUS_CANCELLED = "cancelled"

CASE_ROLE_LEAD = "lead_lawyer"
CASE_ROLE_PARTNER = "partner"

STEP_TO_CASE_ROLE = {
    TASK_STEP_LEAD: CASE_ROLE_LEAD,
    TASK_STEP_PARTNER: CASE_ROLE_PARTNER,
}


class ApprovalStore:
    def __init__(self, db_path: str, rbac_store=None):
        self.db_path = db_path
        self.rbac = rbac_store

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def ensure_schema(self) -> None:
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS doc_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                title TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                created_by INTEGER,
                source TEXT NOT NULL,
                approval_status TEXT NOT NULL DEFAULT 'draft',
                reject_comment TEXT,
                session_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approval_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_id INTEGER NOT NULL,
                case_id INTEGER NOT NULL,
                assignee_user_id INTEGER NOT NULL,
                step TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                decision TEXT,
                comment TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                FOREIGN KEY (artifact_id) REFERENCES doc_artifacts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_approval_tasks_assignee_status
                ON approval_tasks(assignee_user_id, status);
            CREATE INDEX IF NOT EXISTS idx_approval_tasks_artifact
                ON approval_tasks(artifact_id, status);
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER,
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id INTEGER,
                case_id INTEGER,
                detail_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_events_case
                ON audit_events(case_id, created_at);
            CREATE TABLE IF NOT EXISTS rejection_acks (
                user_id INTEGER NOT NULL,
                artifact_id INTEGER NOT NULL,
                acked_at TEXT NOT NULL,
                PRIMARY KEY (user_id, artifact_id),
                FOREIGN KEY (artifact_id) REFERENCES doc_artifacts(id) ON DELETE CASCADE
            );
            """
        )
        try:
            conn.execute("ALTER TABLE doc_artifacts ADD COLUMN session_id TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _enrich_artifact(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return dict(row)

    def _enrich_task(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return dict(row)

    def _enrich_audit(self, row: Dict[str, Any]) -> Dict[str, Any]:
        item = dict(row)
        raw = item.pop("detail_json", None)
        if raw:
            try:
                item["detail"] = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError, json.JSONDecodeError):
                item["detail"] = {}
        else:
            item["detail"] = {}
        return item

    def create_artifact(
        self,
        case_id: int,
        file_id: str,
        title: str,
        doc_type: str,
        created_by: Optional[int] = None,
        source: str = "ai_draft_doc",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM doc_artifacts
            WHERE case_id = ? AND doc_type = ?
            """,
            (case_id, doc_type),
        )
        version = int(cur.fetchone()["next_version"])
        sid = (session_id or "").strip() or None
        cur.execute(
            """
            INSERT INTO doc_artifacts (
                case_id, file_id, version, title, doc_type, created_by, source,
                approval_status, reject_comment, session_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                case_id,
                file_id,
                version,
                title,
                doc_type,
                created_by,
                source,
                ARTIFACT_STATUS_DRAFT,
                sid,
                now,
                now,
            ),
        )
        conn.commit()
        artifact_id = cur.lastrowid
        conn.close()
        return self.get_artifact(artifact_id)  # type: ignore[return-value]

    def get_artifact(self, artifact_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM doc_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        conn.close()
        return self._enrich_artifact(dict(row)) if row else None

    def get_artifact_by_file_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM doc_artifacts WHERE file_id = ? ORDER BY id DESC LIMIT 1",
            (file_id,),
        ).fetchone()
        conn.close()
        return self._enrich_artifact(dict(row)) if row else None

    def list_artifacts_for_case(self, case_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM doc_artifacts WHERE case_id = ? ORDER BY id DESC",
            (case_id,),
        ).fetchall()
        conn.close()
        return [self._enrich_artifact(dict(r)) for r in rows]

    def _member_user_id(self, case_id: int, role_code: str) -> Optional[int]:
        if not self.rbac:
            return None
        for member in self.rbac.list_case_members(case_id):
            if member.get("role_code") == role_code:
                return int(member["user_id"])
        return None

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM approval_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        conn.close()
        return self._enrich_task(dict(row)) if row else None

    def _get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        return self.get_task(task_id)

    def _create_task(
        self,
        cur: sqlite3.Cursor,
        *,
        artifact_id: int,
        case_id: int,
        assignee_user_id: int,
        step: str,
        now: str,
    ) -> int:
        cur.execute(
            """
            INSERT INTO approval_tasks (
                artifact_id, case_id, assignee_user_id, step, status,
                decision, comment, created_at, decided_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, NULL)
            """,
            (artifact_id, case_id, assignee_user_id, step, TASK_STATUS_OPEN, now),
        )
        return int(cur.lastrowid)

    def _cancel_open_tasks_for_artifact(
        self, cur: sqlite3.Cursor, artifact_id: int, except_task_id: Optional[int] = None
    ) -> None:
        if except_task_id is not None:
            cur.execute(
                """
                UPDATE approval_tasks
                SET status = ?, decided_at = COALESCE(decided_at, ?)
                WHERE artifact_id = ? AND status = ? AND id != ?
                """,
                (TASK_STATUS_CANCELLED, self._now(), artifact_id, TASK_STATUS_OPEN, except_task_id),
            )
        else:
            cur.execute(
                """
                UPDATE approval_tasks
                SET status = ?, decided_at = COALESCE(decided_at, ?)
                WHERE artifact_id = ? AND status = ?
                """,
                (TASK_STATUS_CANCELLED, self._now(), artifact_id, TASK_STATUS_OPEN),
            )

    def submit_for_review(
        self,
        artifact_id: int,
        actor_user_id: int,
        actor_case_role: str,
    ) -> Dict[str, Any]:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise ValueError("artifact not found")
        if artifact["approval_status"] != ARTIFACT_STATUS_DRAFT:
            raise ValueError("artifact is not in draft status")

        case_id = int(artifact["case_id"])
        now = self._now()

        if actor_case_role == CASE_ROLE_LEAD:
            next_status = ARTIFACT_STATUS_PENDING_PARTNER
            next_step = TASK_STEP_PARTNER
        else:
            next_status = ARTIFACT_STATUS_PENDING_LEAD
            next_step = TASK_STEP_LEAD

        role_code = STEP_TO_CASE_ROLE[next_step]
        assignee_user_id = self._member_user_id(case_id, role_code)
        if assignee_user_id is None:
            raise ValueError(f"case has no {role_code}")

        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE doc_artifacts
            SET approval_status = ?, reject_comment = NULL, updated_at = ?
            WHERE id = ?
            """,
            (next_status, now, artifact_id),
        )
        self._create_task(
            cur,
            artifact_id=artifact_id,
            case_id=case_id,
            assignee_user_id=assignee_user_id,
            step=next_step,
            now=now,
        )
        conn.commit()
        conn.close()

        self.write_audit(
            actor_user_id=actor_user_id,
            action="artifact_submit",
            object_type="doc_artifact",
            object_id=artifact_id,
            case_id=case_id,
            detail={
                "approval_status": next_status,
                "step": next_step,
                "assignee_user_id": assignee_user_id,
            },
        )
        return self.get_artifact(artifact_id)  # type: ignore[return-value]

    def decide(
        self,
        task_id: int,
        actor_user_id: int,
        decision: str,
        comment: str = "",
        *,
        allow_non_assignee: bool = False,
    ) -> Dict[str, Any]:
        task = self._get_task(task_id)
        if not task:
            raise ValueError("task not found")

        artifact_id = int(task["artifact_id"])
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise ValueError("artifact not found")

        if task["status"] == TASK_STATUS_DONE:
            return artifact

        if task["status"] != TASK_STATUS_OPEN:
            raise ValueError("task is not open")
        if int(task["assignee_user_id"]) != int(actor_user_id) and not allow_non_assignee:
            raise ValueError("not task assignee")
        if decision not in ("approve", "reject"):
            raise ValueError("invalid decision")

        now = self._now()
        case_id = int(task["case_id"])
        conn = self._connect()
        cur = conn.cursor()

        if decision == "reject":
            cur.execute(
                """
                UPDATE approval_tasks
                SET status = ?, decision = ?, comment = ?, decided_at = ?
                WHERE id = ?
                """,
                (TASK_STATUS_DONE, "reject", comment or None, now, task_id),
            )
            self._cancel_open_tasks_for_artifact(cur, artifact_id, except_task_id=task_id)
            cur.execute(
                """
                UPDATE doc_artifacts
                SET approval_status = ?, reject_comment = ?, updated_at = ?
                WHERE id = ?
                """,
                (ARTIFACT_STATUS_DRAFT, comment or None, now, artifact_id),
            )
            self.clear_rejection_acks_for_artifact(artifact_id, cur=cur)
            conn.commit()
            conn.close()
            self.write_audit(
                actor_user_id=actor_user_id,
                action="approval_reject",
                object_type="approval_task",
                object_id=task_id,
                case_id=case_id,
                detail={
                    "artifact_id": artifact_id,
                    "step": task["step"],
                    "comment": comment,
                },
            )
            return self.get_artifact(artifact_id)  # type: ignore[return-value]

        cur.execute(
            """
            UPDATE approval_tasks
            SET status = ?, decision = ?, comment = ?, decided_at = ?
            WHERE id = ?
            """,
            (TASK_STATUS_DONE, "approve", comment or None, now, task_id),
        )

        if task["step"] == TASK_STEP_LEAD:
            next_status = ARTIFACT_STATUS_PENDING_PARTNER
            assignee_user_id = self._member_user_id(case_id, CASE_ROLE_PARTNER)
            if assignee_user_id is None:
                conn.rollback()
                conn.close()
                raise ValueError("case has no partner")
            cur.execute(
                """
                UPDATE doc_artifacts
                SET approval_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status, now, artifact_id),
            )
            self._create_task(
                cur,
                artifact_id=artifact_id,
                case_id=case_id,
                assignee_user_id=assignee_user_id,
                step=TASK_STEP_PARTNER,
                now=now,
            )
        elif task["step"] == TASK_STEP_PARTNER:
            cur.execute(
                """
                UPDATE doc_artifacts
                SET approval_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (ARTIFACT_STATUS_APPROVED, now, artifact_id),
            )
        else:
            conn.rollback()
            conn.close()
            raise ValueError(f"unknown task step: {task['step']}")

        conn.commit()
        conn.close()
        self.write_audit(
            actor_user_id=actor_user_id,
            action="approval_approve",
            object_type="approval_task",
            object_id=task_id,
            case_id=case_id,
            detail={
                "artifact_id": artifact_id,
                "step": task["step"],
                "comment": comment,
            },
        )
        return self.get_artifact(artifact_id)  # type: ignore[return-value]

    def list_rejected_for_creator(self, user_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT *
            FROM doc_artifacts
            WHERE created_by = ?
              AND approval_status = ?
              AND reject_comment IS NOT NULL
              AND TRIM(reject_comment) != ''
            ORDER BY updated_at DESC, id DESC
            """,
            (user_id, ARTIFACT_STATUS_DRAFT),
        ).fetchall()
        conn.close()
        return [self._enrich_artifact(dict(r)) for r in rows]

    def is_rejection_acked(self, user_id: int, artifact_id: int) -> bool:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT 1
            FROM rejection_acks
            WHERE user_id = ? AND artifact_id = ?
            """,
            (user_id, artifact_id),
        ).fetchone()
        conn.close()
        return row is not None

    def ack_rejection(self, user_id: int, artifact_id: int) -> None:
        now = self._now()
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO rejection_acks (user_id, artifact_id, acked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, artifact_id) DO UPDATE SET acked_at = excluded.acked_at
            """,
            (user_id, artifact_id, now),
        )
        conn.commit()
        conn.close()

    def clear_rejection_acks_for_artifact(
        self,
        artifact_id: int,
        *,
        cur: Optional[sqlite3.Cursor] = None,
    ) -> None:
        if cur is not None:
            cur.execute(
                "DELETE FROM rejection_acks WHERE artifact_id = ?",
                (artifact_id,),
            )
            return

        conn = self._connect()
        conn.execute(
            "DELETE FROM rejection_acks WHERE artifact_id = ?",
            (artifact_id,),
        )
        conn.commit()
        conn.close()

    def list_open_tasks_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT t.*, a.title AS artifact_title, a.doc_type, a.approval_status, a.file_id
            FROM approval_tasks t
            JOIN doc_artifacts a ON a.id = t.artifact_id
            WHERE t.assignee_user_id = ? AND t.status = ?
            ORDER BY t.created_at DESC
            """,
            (user_id, TASK_STATUS_OPEN),
        ).fetchall()
        conn.close()
        return [self._enrich_task(dict(r)) for r in rows]

    def write_audit(
        self,
        *,
        actor_user_id: Optional[int],
        action: str,
        object_type: str,
        object_id: Optional[int] = None,
        case_id: Optional[int] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_events (
                actor_user_id, action, object_type, object_id, case_id,
                detail_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_user_id,
                action,
                object_type,
                object_id,
                case_id,
                json.dumps(detail or {}, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
        event_id = cur.lastrowid
        conn.close()
        events = self.list_audit(limit=1)
        for event in events:
            if event["id"] == event_id:
                return event
        return {
            "id": event_id,
            "actor_user_id": actor_user_id,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "case_id": case_id,
            "detail": detail or {},
            "created_at": now,
        }

    def list_audit(
        self,
        *,
        case_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        conn = self._connect()
        if case_id is not None:
            rows = conn.execute(
                """
                SELECT * FROM audit_events
                WHERE case_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (case_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM audit_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        conn.close()
        return [self._enrich_audit(dict(r)) for r in rows]
