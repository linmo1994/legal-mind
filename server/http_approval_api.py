"""HTTP handlers for document artifact registration and approval workflows."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from approval_store import (
    ApprovalStore,
    TASK_STATUS_OPEN,
    TASK_STEP_PARTNER,
)
from auth_service import AuthService
from http_rbac_api import StatusPayload, _deny, _ok, extract_bearer
from rbac_service import RbacService
from rbac_store import RbacStore

DIRECTOR_MAY_APPROVE_PARTNER = True

ApprovalRoute = Tuple[Optional[str], Optional[str]]


def parse_approval_path(path: str, method: str) -> ApprovalRoute:
    """Parse approval API routes. Path should already be stripped of query string."""
    path = (path or "").split("?", 1)[0].rstrip("/") or "/"
    method = (method or "").upper()

    if path == "/api/artifacts" and method == "POST":
        return ("create_artifact", None)
    if path == "/api/approvals/inbox" and method == "GET":
        return ("inbox", None)
    if path == "/api/audit" and method == "GET":
        return ("audit", None)

    if path.startswith("/api/artifacts/") and path.endswith("/submit") and method == "POST":
        parts = path.split("/")
        if len(parts) == 5:
            return ("submit_artifact", parts[3])
    if path.startswith("/api/artifacts/") and method == "GET":
        parts = path.split("/")
        if len(parts) == 4:
            return ("get_artifact", parts[3])

    if path.startswith("/api/approvals/") and path.endswith("/decide") and method == "POST":
        parts = path.split("/")
        if len(parts) == 5:
            return ("decide", parts[3])

    return (None, None)


class ApprovalHttpApi:
    def __init__(
        self,
        store: RbacStore,
        auth: AuthService,
        rbac: RbacService,
        approval_store: ApprovalStore,
    ):
        self.store = store
        self.auth = auth
        self.rbac = rbac
        self.approval_store = approval_store

    def current_user(self, authorization: Optional[str]) -> Optional[Dict[str, Any]]:
        token = extract_bearer(authorization)
        if not token:
            return None
        return self.auth.resolve_token(token)

    def require_user(self, authorization: Optional[str]) -> StatusPayload:
        user = self.current_user(authorization)
        if not user:
            return _deny(401, "未登录或登录已过期")
        return _ok({"user": user})

    def _is_director(self, user_id: int) -> bool:
        return "director" in self.store.list_user_role_codes(user_id)

    def _require_case_member(
        self, authorization: Optional[str], case_id: int
    ) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        member = self.store.get_case_member(case_id, user["id"])
        if not member:
            return _deny(403, "无权操作该案件")
        return _ok({"user": user, "member": member})

    def _require_artifact_access(
        self, authorization: Optional[str], artifact_id: int
    ) -> StatusPayload:
        artifact = self.approval_store.get_artifact(artifact_id)
        if not artifact:
            return _deny(404, "文书不存在")
        gated = self._require_case_member(authorization, int(artifact["case_id"]))
        if gated[0] != 200:
            return gated
        return _ok({"user": gated[1]["user"], "member": gated[1]["member"], "artifact": artifact})

    def create_artifact(
        self, authorization: Optional[str], body: Dict[str, Any]
    ) -> StatusPayload:
        raw_case_id = body.get("case_id")
        if raw_case_id is None:
            return _deny(400, "case_id 必填")
        try:
            case_id = int(raw_case_id)
        except (TypeError, ValueError):
            return _deny(400, "case_id 无效")
        if not self.store.get_case(case_id):
            return _deny(404, "案件不存在")

        gated = self._require_case_member(authorization, case_id)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]

        file_id = (body.get("file_id") or "").strip()
        title = (body.get("title") or "").strip()
        doc_type = (body.get("doc_type") or title or "法律文书").strip()
        source = (body.get("source") or "ai_draft_doc").strip()
        if not file_id:
            return _deny(400, "file_id 必填")
        if not title:
            return _deny(400, "title 必填")

        artifact = self.approval_store.create_artifact(
            case_id=case_id,
            file_id=file_id,
            title=title,
            doc_type=doc_type,
            created_by=user["id"],
            source=source,
        )
        self.approval_store.write_audit(
            actor_user_id=user["id"],
            action="artifact_created",
            object_type="doc_artifact",
            object_id=artifact["id"],
            case_id=case_id,
            detail={"file_id": file_id, "title": title, "doc_type": doc_type},
        )
        return _ok({"artifact": artifact}, 201)

    def get_artifact(
        self, authorization: Optional[str], artifact_id: int
    ) -> StatusPayload:
        gated = self._require_artifact_access(authorization, artifact_id)
        if gated[0] != 200:
            return gated
        return _ok({"artifact": gated[1]["artifact"]})

    def submit_artifact(
        self, authorization: Optional[str], artifact_id: int
    ) -> StatusPayload:
        gated = self._require_artifact_access(authorization, artifact_id)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        member = gated[1]["member"]
        actor_case_role = member.get("role_code") or ""
        if not actor_case_role:
            return _deny(403, "无权提交审核")

        try:
            artifact = self.approval_store.submit_for_review(
                artifact_id,
                actor_user_id=user["id"],
                actor_case_role=actor_case_role,
            )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                return _deny(404, "文书不存在")
            if "draft" in msg:
                return _deny(400, "文书不在草稿状态，无法提交")
            return _deny(400, msg)
        return _ok({"artifact": artifact})

    def inbox(self, authorization: Optional[str]) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        tasks = self.approval_store.list_open_tasks_for_user(user["id"])
        return _ok({"tasks": tasks})

    def decide(
        self,
        authorization: Optional[str],
        task_id: int,
        body: Dict[str, Any],
    ) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]

        task = self.approval_store.get_task(task_id)
        if not task:
            return _deny(404, "待办不存在")

        decision = (body.get("decision") or "").strip()
        comment = (body.get("comment") or "").strip()
        if decision not in ("approve", "reject"):
            return _deny(400, "decision 必须是 approve 或 reject")

        is_assignee = int(task.get("assignee_user_id") or 0) == int(user["id"])
        allow_proxy = False
        if not is_assignee:
            if (
                DIRECTOR_MAY_APPROVE_PARTNER
                and task.get("step") == TASK_STEP_PARTNER
                and task.get("status") == TASK_STATUS_OPEN
                and self._is_director(user["id"])
            ):
                allow_proxy = True
            else:
                return _deny(403, "无权处理该待办")

        try:
            artifact = self.approval_store.decide(
                task_id,
                actor_user_id=user["id"],
                decision=decision,
                comment=comment,
                allow_non_assignee=allow_proxy,
            )
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                return _deny(404, "待办不存在")
            if "not open" in msg:
                return _deny(400, "待办已关闭")
            if "assignee" in msg:
                return _deny(403, "无权处理该待办")
            return _deny(400, msg)
        return _ok({"artifact": artifact})

    def list_audit(
        self, authorization: Optional[str], case_id: Optional[int]
    ) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        if case_id is None:
            return _deny(400, "case_id 必填")
        if not self.store.get_case(case_id):
            return _deny(404, "案件不存在")

        is_director = self._is_director(user["id"])
        member = self.store.get_case_member(case_id, user["id"])
        is_partner = bool(member and member.get("role_code") == "partner")
        if not is_director and not is_partner:
            return _deny(403, "无权查看审计日志")

        events = self.approval_store.list_audit(case_id=case_id)
        return _ok({"events": events})
