"""HTTP handlers for auth and RBAC admin APIs (testable without socket server)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from auth_service import AuthService
from rbac_service import RbacService
from rbac_store import CASE_TRACK_ROLES, RbacStore

StatusPayload = Tuple[int, Dict[str, Any]]


def _deny(status: int, message: str) -> StatusPayload:
    return status, {"error": message}


def _ok(payload: Dict[str, Any], status: int = 200) -> StatusPayload:
    return status, payload


def extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


class RbacHttpApi:
    def __init__(self, store: RbacStore, auth: AuthService, rbac: RbacService):
        self.store = store
        self.auth = auth
        self.rbac = rbac

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

    def require_perm(
        self,
        authorization: Optional[str],
        perm: str,
        case_id: Optional[int] = None,
    ) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        if not self.rbac.require(user["id"], perm, case_id):
            return _deny(403, f"无权限：{perm}")
        return _ok({"user": user})

    def login(self, body: Dict[str, Any]) -> StatusPayload:
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not username or not password:
            return _deny(400, "请输入用户名和密码")
        out = self.auth.login(username, password)
        if not out:
            return _deny(401, "用户名或密码错误")
        return _ok(out)

    def logout(self, authorization: Optional[str]) -> StatusPayload:
        token = extract_bearer(authorization)
        if token:
            self.auth.logout(token)
        return _ok({"ok": True})

    def me(self, authorization: Optional[str], case_id: Optional[int] = None) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        firm = self.auth.firm_roles_and_permissions(user["id"])
        payload: Dict[str, Any] = {"user": user, **firm}
        if case_id is not None:
            role = self.store.case_role_code(user["id"], case_id)
            payload["case_id"] = case_id
            payload["case_role"] = role
            payload["case_permissions"] = sorted(self.rbac.case_permissions(user["id"], case_id))
            payload["effective_permissions"] = sorted(
                self.rbac.effective_permissions(user["id"], case_id)
            )
        return _ok(payload)

    def list_users(self, authorization: Optional[str]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.user_manage")
        if gated[0] != 200:
            # 分案场景：行政主管可拉取可入案人员简表
            gated2 = self.require_perm(authorization, "cap.case_assign")
            if gated2[0] != 200:
                return gated
            users = []
            for u in self.store.list_users():
                roles = self.store.list_user_role_codes(u["id"])
                if set(roles) & {"director", "admin_officer"}:
                    continue
                users.append({
                    "id": u["id"],
                    "username": u["username"],
                    "display_name": u["display_name"],
                    "roles": roles,
                    "is_active": bool(u.get("is_active")),
                })
            return _ok({"users": users})
        users = []
        for u in self.store.list_users():
            item = dict(u)
            item["roles"] = self.store.list_user_role_codes(u["id"])
            item["is_active"] = bool(item.get("is_active"))
            item["must_change_password"] = bool(item.get("must_change_password"))
            users.append(item)
        return _ok({"users": users})

    def create_user(self, authorization: Optional[str], body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.user_manage")
        if gated[0] != 200:
            return gated
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        display_name = (body.get("display_name") or username).strip()
        role_codes = body.get("roles") or body.get("role_codes") or []
        if not username or not password:
            return _deny(400, "username 与 password 必填")
        if self.store.get_user_by_username(username):
            return _deny(409, "用户名已存在")
        try:
            user = self.store.create_user(
                username,
                self.auth.hash_password(password),
                display_name=display_name,
                must_change_password=bool(body.get("must_change_password", True)),
            )
            if role_codes:
                self.store.set_user_roles(user["id"], list(role_codes))
        except ValueError as exc:
            return _deny(400, str(exc))
        user["roles"] = self.store.list_user_role_codes(user["id"])
        user.pop("password_hash", None)
        return _ok({"user": user}, 201)

    def update_user(self, authorization: Optional[str], user_id: int, body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.user_manage")
        if gated[0] != 200:
            return gated
        user = self.store.get_user_by_id(user_id)
        if not user:
            return _deny(404, "用户不存在")
        if "is_active" in body:
            self.store.set_user_active(user_id, bool(body["is_active"]))
        if body.get("password"):
            self.store.update_password_hash(
                user_id,
                self.auth.hash_password(body["password"]),
                must_change=bool(body.get("must_change_password", False)),
            )
        if "roles" in body or "role_codes" in body:
            codes = body.get("roles") or body.get("role_codes") or []
            try:
                self.store.set_user_roles(user_id, list(codes))
            except ValueError as exc:
                return _deny(400, str(exc))
        updated = self.store.get_user_by_id(user_id)
        assert updated is not None
        public = {
            "id": updated["id"],
            "username": updated["username"],
            "display_name": updated["display_name"],
            "is_active": bool(updated["is_active"]),
            "must_change_password": bool(updated["must_change_password"]),
            "roles": self.store.list_user_role_codes(user_id),
        }
        return _ok({"user": public})

    def list_roles(self, authorization: Optional[str]) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        # viewing roles: any logged-in admin-ish; require role_manage OR user_manage OR login
        roles = []
        for r in self.store.list_roles():
            item = dict(r)
            item["permissions"] = self.store.list_role_permission_codes(r["code"])
            item["is_system"] = bool(item.get("is_system"))
            roles.append(item)
        return _ok({"roles": roles})

    def update_role(self, authorization: Optional[str], role_code: str, body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.role_manage")
        if gated[0] != 200:
            return gated
        role = self.store.get_role_by_code(role_code)
        if not role:
            return _deny(404, "角色不存在")
        if "permissions" in body or "permission_codes" in body:
            codes = body.get("permissions") or body.get("permission_codes") or []
            try:
                self.store.set_role_permissions(role_code, list(codes))
            except ValueError as exc:
                return _deny(400, str(exc))
        if "description" in body:
            conn = self.store._connect()
            conn.execute(
                "UPDATE roles SET description = ? WHERE code = ?",
                (body.get("description") or "", role_code),
            )
            conn.commit()
            conn.close()
        role = self.store.get_role_by_code(role_code)
        assert role is not None
        role["permissions"] = self.store.list_role_permission_codes(role_code)
        role["is_system"] = bool(role.get("is_system"))
        return _ok({"role": role})

    def list_permissions(self, authorization: Optional[str]) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        return _ok({"permissions": self.store.list_permissions()})

    def update_permission(self, authorization: Optional[str], code: str, body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.perm_manage")
        if gated[0] != 200:
            return gated
        updated = self.store.update_permission_meta(
            code,
            name=body.get("name"),
            group_name=body.get("group_name"),
            description=body.get("description"),
        )
        if not updated:
            return _deny(404, "功能不存在")
        return _ok({"permission": updated})

    def list_cases(self, authorization: Optional[str], mine: bool = False) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        can_all = self.rbac.require(user["id"], "cap.case_manage")
        if mine or not can_all:
            cases = self.store.list_cases_for_user(user["id"], all_cases=False)
            # directors with case_manage but mine=1 still see only membership — if none, show all when can_all and not mine
        else:
            cases = self.store.list_cases_for_user(user["id"], all_cases=True)
        return _ok({"cases": cases})

    def create_case(self, authorization: Optional[str], body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        case_no = (body.get("case_no") or "").strip()
        title = (body.get("title") or "").strip()
        if not case_no or not title:
            return _deny(400, "case_no 与 title 必填")
        try:
            case = self.store.create_case(case_no, title, created_by=user["id"])
        except Exception as exc:
            return _deny(400, f"创建案件失败: {exc}")
        return _ok({"case": case}, 201)

    def get_case(self, authorization: Optional[str], case_id: int) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        case = self.store.get_case(case_id)
        if not case:
            return _deny(404, "案件不存在")
        can_all = self.rbac.require(user["id"], "cap.case_manage")
        member = self.store.get_case_member(case_id, user["id"])
        if not can_all and not member:
            return _deny(403, "无权查看该案件")
        return _ok({"case": case, "members": self.store.list_case_members(case_id)})

    def update_case(self, authorization: Optional[str], case_id: int, body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        case = self.store.update_case(
            case_id,
            title=body.get("title"),
            status=body.get("status"),
            case_no=body.get("case_no"),
        )
        if not case:
            return _deny(404, "案件不存在")
        return _ok({"case": case})

    def add_member(self, authorization: Optional[str], case_id: int, body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_assign")
        if gated[0] != 200:
            return gated
        actor = gated[1]["user"]
        user_id = body.get("user_id")
        role_code = body.get("role_code") or body.get("role")
        if not user_id or not role_code:
            return _deny(400, "user_id 与 role_code 必填")
        if role_code not in CASE_TRACK_ROLES:
            return _deny(400, "案级角色必须是 partner / lead_lawyer / assistant")
        try:
            member = self.store.add_case_member(
                int(case_id), int(user_id), str(role_code), assigned_by=actor["id"]
            )
        except ValueError as exc:
            return _deny(400, str(exc))
        return _ok({"member": member}, 201)

    def remove_member(self, authorization: Optional[str], case_id: int, user_id: int) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_assign")
        if gated[0] != 200:
            return gated
        self.store.remove_case_member(case_id, user_id)
        return _ok({"ok": True})

    def check_orchestrate_access(
        self, authorization: Optional[str], body: Dict[str, Any]
    ) -> StatusPayload:
        gated = self.require_user(authorization)
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        case_id = body.get("case_id")
        if case_id is None or case_id == "":
            return _deny(400, "业务请求需要 case_id")
        case_id = int(case_id)
        if not self.store.get_case(case_id):
            return _deny(404, "案件不存在")
        if not self.rbac.require(user["id"], "cap.chat", case_id):
            return _deny(403, "无权限：cap.chat")
        text = (body.get("user_text") or body.get("message") or "")
        if any(k in text for k in ("断案", "审判", "裁判分析")) and not self.rbac.require(
            user["id"], "cap.judge", case_id
        ):
            return _deny(403, "无权限：cap.judge")
        if any(k in text for k in ("起诉状", "生成文书", "起草", "判决书")) and not self.rbac.require(
            user["id"], "cap.doc_write", case_id
        ):
            return _deny(403, "无权限：cap.doc_write")
        return _ok({"user": user, "case_id": case_id})
