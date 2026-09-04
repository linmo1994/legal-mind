"""HTTP handlers for auth and RBAC admin APIs (testable without socket server)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from auth_service import AuthService
from rbac_service import RbacService
from rbac_store import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_CODES,
    CASE_CONTRACT_FILE_MAX,
    CASE_EVIDENCE_FILE_MAX,
    CASE_STATUS_ASSIGNED,
    CASE_STATUS_CODES,
    CASE_STATUSES,
    CASE_TRACK_ROLES,
    CASE_TYPE_CODES,
    CASE_TYPES,
    CLIENT_TYPE_CODES,
    CLIENT_TYPES,
    FIRM_TRACK_ROLES,
    RbacStore,
    normalize_account_status,
)


def _normalize_file_ids(raw: Any) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    out: List[str] = []
    seen = set()
    for x in raw:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _validate_case_file_limits(
    contract_ids: List[str], evidence_ids: List[str]
) -> Optional[str]:
    if len(contract_ids) > CASE_CONTRACT_FILE_MAX:
        return f"委托合同最多上传 {CASE_CONTRACT_FILE_MAX} 份文件"
    if len(evidence_ids) > CASE_EVIDENCE_FILE_MAX:
        return f"证据材料最多上传 {CASE_EVIDENCE_FILE_MAX} 份文件"
    return None

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
                    "account_status": u.get("account_status") or ACCOUNT_STATUS_ACTIVE,
                    "account_status_label": u.get("account_status_label") or "启动",
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
        display_name = (body.get("display_name") or body.get("name") or username).strip()
        role_codes = body.get("roles") or body.get("role_codes") or []
        if isinstance(role_codes, str):
            role_codes = [role_codes] if role_codes else []
        role_codes = [c for c in role_codes if c]
        if not username or not password:
            return _deny(400, "账号与密码必填")
        if not display_name:
            return _deny(400, "姓名必填")
        if self.store.get_user_by_username(username):
            return _deny(409, "用户名已存在")
        bad = [c for c in role_codes if c not in FIRM_TRACK_ROLES]
        if bad:
            return _deny(400, "所级角色仅支持律所主任或行政主管")
        status = normalize_account_status(
            body.get("account_status"),
            bool(body["is_active"]) if "is_active" in body else None,
        )
        if status not in ACCOUNT_STATUS_CODES:
            return _deny(400, "无效的账号状态")
        try:
            user = self.store.create_user(
                username,
                self.auth.hash_password(password),
                display_name=display_name,
                must_change_password=bool(body.get("must_change_password", True)),
                account_status=status,
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
        display_name = body.get("display_name") if "display_name" in body else body.get("name")
        if "account_status" in body or "is_active" in body or display_name is not None:
            status = None
            if "account_status" in body:
                status = normalize_account_status(body.get("account_status"))
                if status not in ACCOUNT_STATUS_CODES:
                    return _deny(400, "无效的账号状态")
            try:
                self.store.update_user_profile(
                    user_id,
                    display_name=display_name.strip() if isinstance(display_name, str) else display_name,
                    account_status=status,
                    is_active=bool(body["is_active"]) if "is_active" in body and status is None else None,
                )
            except ValueError as exc:
                return _deny(400, str(exc))
        if body.get("password"):
            self.store.update_password_hash(
                user_id,
                self.auth.hash_password(body["password"]),
                must_change=bool(body.get("must_change_password", False)),
            )
        if "roles" in body or "role_codes" in body:
            codes = body.get("roles") or body.get("role_codes") or []
            if isinstance(codes, str):
                codes = [codes] if codes else []
            codes = [c for c in codes if c]
            bad = [c for c in codes if c not in FIRM_TRACK_ROLES]
            if bad:
                return _deny(400, "所级角色仅支持律所主任或行政主管")
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
            "account_status": updated.get("account_status"),
            "account_status_label": updated.get("account_status_label"),
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
        return _ok({
            "cases": cases,
            "case_statuses": [{"code": c, "label": lab} for c, lab in CASE_STATUSES],
            "case_types": [
                {"code": c, "label": lab, "abbr": abbr} for c, lab, abbr in CASE_TYPES
            ],
        })

    def preview_case_no(self, authorization: Optional[str], case_type: str) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        case_type = (case_type or "").strip()
        if case_type not in CASE_TYPE_CODES:
            return _deny(400, "无效的案件类型")
        try:
            case_no = self.store.next_case_no(case_type)
        except ValueError as exc:
            return _deny(400, str(exc))
        return _ok({"case_no": case_no, "case_type": case_type})

    def create_case(self, authorization: Optional[str], body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        if not self.rbac.require(gated[1]["user"]["id"], "cap.case_assign"):
            return _deny(403, "无权限：cap.case_assign")
        user = gated[1]["user"]
        title = (body.get("title") or "").strip()
        case_type = (body.get("case_type") or "").strip()
        case_no = (body.get("case_no") or "").strip()
        if not title:
            return _deny(400, "标题必填")
        if case_type not in CASE_TYPE_CODES:
            return _deny(400, "请选择案件类型：民事、刑事、行政、执行")

        # Prefer structured fields; also accept members: [{user_id, role_code}, ...]
        # 助理可选；合伙人、主办律师必填
        role_user: Dict[str, Any] = {
            "partner": body.get("partner_user_id"),
            "lead_lawyer": body.get("lead_lawyer_user_id"),
            "assistant": body.get("assistant_user_id"),
        }
        for item in body.get("members") or []:
            code = item.get("role_code") or item.get("role")
            if code in role_user and item.get("user_id"):
                role_user[code] = item.get("user_id")

        required_missing = [k for k in ("partner", "lead_lawyer") if not role_user.get(k)]
        if required_missing:
            labels = {"partner": "合伙人", "lead_lawyer": "主办律师"}
            names = "、".join(labels[m] for m in required_missing)
            return _deny(400, f"新建案件须同时分配：{names}")

        try:
            partner_id = int(role_user["partner"])
            lead_id = int(role_user["lead_lawyer"])
        except (TypeError, ValueError):
            return _deny(400, "分案用户 ID 无效")
        if partner_id == lead_id:
            return _deny(400, "合伙人与主办律师必须是不同用户")

        assistant_id: Optional[int] = None
        if role_user.get("assistant") not in (None, ""):
            try:
                assistant_id = int(role_user["assistant"])
            except (TypeError, ValueError):
                return _deny(400, "助理用户 ID 无效")
            if assistant_id in (partner_id, lead_id):
                return _deny(400, "助理不能与合伙人或主办律师为同一人")

        try:
            if not case_no:
                case_no = self.store.next_case_no(case_type)
            contract_ids = _normalize_file_ids(body.get("contract_file_ids"))
            evidence_ids = _normalize_file_ids(body.get("evidence_file_ids"))
            limit_err = _validate_case_file_limits(contract_ids, evidence_ids)
            if limit_err:
                return _deny(400, limit_err)
            meta = {
                "case_type": case_type,
                "contract_file_ids": contract_ids,
                "evidence_file_ids": evidence_ids,
            }
            case = self.store.create_case(
                case_no,
                title,
                created_by=user["id"],
                status=CASE_STATUS_ASSIGNED,
                meta_json=json.dumps(meta, ensure_ascii=False),
            )
        except Exception as exc:
            return _deny(400, f"创建案件失败: {exc}")

        client_ids_raw = body.get("client_ids") or []
        if not isinstance(client_ids_raw, list):
            client_ids_raw = [client_ids_raw] if client_ids_raw else []
        try:
            client_ids = [int(x) for x in client_ids_raw if str(x).strip()]
            clients = self.store.set_case_clients(case["id"], client_ids) if client_ids else []
        except (TypeError, ValueError) as exc:
            try:
                self.store.delete_case(case["id"])
            except Exception:
                pass
            return _deny(400, str(exc))

        assigned = []
        try:
            assignments = [
                ("partner", partner_id),
                ("lead_lawyer", lead_id),
            ]
            if assistant_id is not None:
                assignments.append(("assistant", assistant_id))
            for role_code, uid in assignments:
                member = self.store.add_case_member(
                    case["id"], uid, role_code, assigned_by=user["id"]
                )
                assigned.append(member)
        except ValueError as exc:
            # best-effort cleanup
            try:
                self.store.delete_case(case["id"])
            except Exception:
                pass
            return _deny(400, str(exc))

        return _ok(
            {
                "case": case,
                "members": assigned,
                "clients": clients,
                "case_statuses": [{"code": c, "label": lab} for c, lab in CASE_STATUSES],
            },
            201,
        )

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
        return _ok({
            "case": case,
            "members": self.store.list_case_members(case_id),
            "clients": self.store.list_case_clients(case_id),
        })

    def update_case(self, authorization: Optional[str], case_id: int, body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        case = self.store.get_case(case_id)
        if not case:
            return _deny(404, "案件不存在")
        if body.get("status") is not None and body.get("status") not in CASE_STATUS_CODES:
            return _deny(400, "无效的案件状态")

        meta = dict(case.get("meta") or {})
        meta_changed = False
        if "case_type" in body and body.get("case_type"):
            ctype = str(body.get("case_type")).strip()
            if ctype not in CASE_TYPE_CODES:
                return _deny(400, "无效的案件类型")
            meta["case_type"] = ctype
            meta_changed = True
        if "contract_file_ids" in body:
            meta["contract_file_ids"] = _normalize_file_ids(body.get("contract_file_ids"))
            meta_changed = True
        if "evidence_file_ids" in body:
            meta["evidence_file_ids"] = _normalize_file_ids(body.get("evidence_file_ids"))
            meta_changed = True
        if "append_contract_file_ids" in body:
            cur = _normalize_file_ids(meta.get("contract_file_ids"))
            for s in _normalize_file_ids(body.get("append_contract_file_ids")):
                if s not in cur:
                    cur.append(s)
            meta["contract_file_ids"] = cur
            meta_changed = True
        if "append_evidence_file_ids" in body:
            cur = _normalize_file_ids(meta.get("evidence_file_ids"))
            for s in _normalize_file_ids(body.get("append_evidence_file_ids")):
                if s not in cur:
                    cur.append(s)
            meta["evidence_file_ids"] = cur
            meta_changed = True

        limit_err = _validate_case_file_limits(
            _normalize_file_ids(meta.get("contract_file_ids")),
            _normalize_file_ids(meta.get("evidence_file_ids")),
        )
        if limit_err:
            return _deny(400, limit_err)

        try:
            case = self.store.update_case(
                case_id,
                title=body.get("title"),
                status=body.get("status"),
                case_no=body.get("case_no"),
                meta_json=json.dumps(meta, ensure_ascii=False) if meta_changed else None,
            )
        except ValueError as exc:
            return _deny(400, str(exc))
        if not case:
            return _deny(404, "案件不存在")

        clients = self.store.list_case_clients(case_id)
        if "client_ids" in body:
            raw = body.get("client_ids") or []
            if not isinstance(raw, list):
                raw = [raw] if raw else []
            try:
                clients = self.store.set_case_clients(case_id, [int(x) for x in raw if str(x).strip()])
            except (TypeError, ValueError) as exc:
                return _deny(400, str(exc))

        return _ok({
            "case": case,
            "members": self.store.list_case_members(case_id),
            "clients": clients,
        })

    def delete_case(self, authorization: Optional[str], case_id: int) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        if not self.store.delete_case(case_id):
            return _deny(404, "案件不存在")
        return _ok({"ok": True})

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

    def list_clients(self, authorization: Optional[str]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        return _ok({
            "clients": self.store.list_clients(),
            "client_types": [{"code": c, "label": lab} for c, lab in CLIENT_TYPES],
        })

    def get_client(self, authorization: Optional[str], client_id: int) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        client = self.store.get_client(client_id)
        if not client:
            return _deny(404, "客户不存在")
        return _ok({"client": client})

    def create_client(self, authorization: Optional[str], body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        user = gated[1]["user"]
        try:
            client = self.store.create_client(
                name=(body.get("name") or "").strip(),
                client_type=(body.get("client_type") or "").strip(),
                id_number=(body.get("id_number") or "").strip(),
                phone=body.get("phone"),
                email=body.get("email"),
                contact_name=body.get("contact_name"),
                created_by=user["id"],
            )
        except ValueError as exc:
            return _deny(400, str(exc))
        return _ok({"client": client}, 201)

    def update_client(self, authorization: Optional[str], client_id: int, body: Dict[str, Any]) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        try:
            client = self.store.update_client(
                client_id,
                name=body.get("name"),
                client_type=body.get("client_type"),
                id_number=body.get("id_number"),
                phone=body.get("phone"),
                email=body.get("email"),
                contact_name=body.get("contact_name"),
            )
        except ValueError as exc:
            return _deny(400, str(exc))
        if not client:
            return _deny(404, "客户不存在")
        return _ok({"client": client})

    def delete_client(self, authorization: Optional[str], client_id: int) -> StatusPayload:
        gated = self.require_perm(authorization, "cap.case_manage")
        if gated[0] != 200:
            return gated
        if not self.store.delete_client(client_id):
            return _deny(404, "客户不存在")
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
