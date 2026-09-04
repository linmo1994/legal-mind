"""SQLite persistence for RBAC, auth sessions, and cases."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Set


SYSTEM_ROLES = [
    {"code": "director", "name": "律所主任", "track": "firm", "description": "全所最高权限"},
    {"code": "admin_officer", "name": "行政主管", "track": "firm", "description": "分案与案件管理，不办案"},
    {"code": "partner", "name": "合伙人", "track": "case", "description": "案级：入案后按角色授权"},
    {"code": "lead_lawyer", "name": "主办律师", "track": "case", "description": "案级：入案后按角色授权"},
    {"code": "assistant", "name": "助理", "track": "case", "description": "案级：入案后按角色授权"},
]

PERMISSIONS = [
    ("page.home", "首页", "page", "页面"),
    ("page.chat", "对话", "page", "页面"),
    ("page.admin", "管理后台", "page", "页面"),
    ("page.admin.users", "用户管理", "page", "页面"),
    ("page.admin.roles", "角色管理", "page", "页面"),
    ("page.admin.perms", "功能管理", "page", "页面"),
    ("page.admin.cases", "案件管理", "page", "页面"),
    ("page.admin.clients", "客户管理", "page", "页面"),
    ("page.admin.skills", "技能制作", "page", "页面"),
    ("page.admin.mcp", "MCP 配置", "page", "页面"),
    ("page.admin.vectorize", "文档向量化", "page", "页面"),
    ("cap.user_manage", "用户管理", "capability", "管理"),
    ("cap.role_manage", "角色管理", "capability", "管理"),
    ("cap.perm_manage", "功能管理", "capability", "管理"),
    ("cap.case_manage", "案件管理", "capability", "管理"),
    ("cap.case_assign", "分案", "capability", "管理"),
    ("cap.skill_manage", "技能管理", "capability", "管理"),
    ("cap.mcp_manage", "MCP 管理", "capability", "管理"),
    ("cap.vectorize", "向量化", "capability", "管理"),
    ("cap.chat", "对话", "capability", "业务"),
    ("cap.judge", "断案", "capability", "业务"),
    ("cap.doc_write", "文书终稿", "capability", "业务"),
    ("cap.retrieve", "检索", "capability", "业务"),
]

# Default role -> permission codes (spec 4.2)
DEFAULT_ROLE_PERMS = {
    "director": [p[0] for p in PERMISSIONS],
    "admin_officer": [
        "page.home",
        "page.admin",
        "page.admin.cases",
        "page.admin.clients",
        "page.admin.skills",
        "page.admin.mcp",
        "page.admin.vectorize",
        "cap.case_manage",
        "cap.case_assign",
        "cap.skill_manage",
        "cap.mcp_manage",
        "cap.vectorize",
    ],
    "partner": [
        "page.home",
        "page.chat",
        "cap.chat",
        "cap.judge",
        "cap.doc_write",
        "cap.retrieve",
    ],
    "lead_lawyer": [
        "page.home",
        "page.chat",
        "cap.chat",
        "cap.judge",
        "cap.doc_write",
        "cap.retrieve",
    ],
    "assistant": [
        "page.home",
        "page.chat",
        "cap.chat",
        "cap.retrieve",
    ],
}

CASE_TRACK_ROLES = {"partner", "lead_lawyer", "assistant"}
FIRM_TRACK_ROLES = {"director", "admin_officer"}

# 案件状态：code -> 中文名（持久化存 code）
CASE_STATUS_INIT = "init"
CASE_STATUS_ASSIGNED = "assigned"
CASE_STATUS_ANALYZING = "analyzing"
CASE_STATUS_HANDLING = "handling"
CASE_STATUS_CLOSED = "closed"
CASE_STATUSES = [
    (CASE_STATUS_INIT, "初始化"),
    (CASE_STATUS_ASSIGNED, "已分案"),
    (CASE_STATUS_ANALYZING, "分析案情中"),
    (CASE_STATUS_HANDLING, "办理案件中"),
    (CASE_STATUS_CLOSED, "已结案"),
]
CASE_STATUS_CODES = {code for code, _ in CASE_STATUSES}
CASE_STATUS_LABELS = {code: label for code, label in CASE_STATUSES}

# 案件类型：code -> 中文名 / 案号缩写
CASE_TYPE_CIVIL = "civil"
CASE_TYPE_CRIMINAL = "criminal"
CASE_TYPE_ADMINISTRATIVE = "administrative"
CASE_TYPE_ENFORCEMENT = "enforcement"
CASE_TYPES = [
    (CASE_TYPE_CIVIL, "民事", "民"),
    (CASE_TYPE_CRIMINAL, "刑事", "刑"),
    (CASE_TYPE_ADMINISTRATIVE, "行政", "行"),
    (CASE_TYPE_ENFORCEMENT, "执行", "执"),
]
CASE_TYPE_CODES = {code for code, _, _ in CASE_TYPES}
CASE_TYPE_LABELS = {code: label for code, label, _ in CASE_TYPES}
CASE_TYPE_ABBR = {code: abbr for code, _, abbr in CASE_TYPES}

# 案件材料数量上限
CASE_CONTRACT_FILE_MAX = 1
CASE_EVIDENCE_FILE_MAX = 10

# 委托客户类型
CLIENT_TYPE_PERSON = "person"
CLIENT_TYPE_ENTERPRISE = "enterprise"
CLIENT_TYPES = [
    (CLIENT_TYPE_PERSON, "个人"),
    (CLIENT_TYPE_ENTERPRISE, "企业"),
]
CLIENT_TYPE_CODES = {code for code, _ in CLIENT_TYPES}
CLIENT_TYPE_LABELS = {code: label for code, label in CLIENT_TYPES}


def validate_client_id_number(client_type: str, id_number: str) -> str:
    """校验并规范化识别号；不合规时抛出 ValueError。"""
    value = (id_number or "").strip().upper()
    if client_type == CLIENT_TYPE_PERSON:
        # 18 位身份证：17 位数字 + 校验位（数字或 X）
        if len(value) != 18:
            raise ValueError("身份证号须为 18 位")
        if not re.fullmatch(r"\d{17}[\dX]", value):
            raise ValueError("身份证号格式不正确（前 17 位为数字，末位为数字或 X）")
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        check_map = "10X98765432"
        total = sum(int(value[i]) * weights[i] for i in range(17))
        if check_map[total % 11] != value[17]:
            raise ValueError("身份证号校验位不正确")
        return value
    if client_type == CLIENT_TYPE_ENTERPRISE:
        # 18 位统一社会信用代码
        if len(value) != 18:
            raise ValueError("统一社会信用代码须为 18 位")
        if not re.fullmatch(r"[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}", value):
            raise ValueError("统一社会信用代码格式不正确（18 位，不含 I/O/Z/S/V）")
        return value
    raise ValueError("客户类型须为个人或企业")


def enrich_client(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    ctype = item.get("client_type")
    item["client_type_label"] = CLIENT_TYPE_LABELS.get(ctype or "", ctype or "")
    return item


# 账号状态：code -> 中文名
ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_LOCKED = "locked"
ACCOUNT_STATUS_RESIGNED = "resigned"
ACCOUNT_STATUSES = [
    (ACCOUNT_STATUS_ACTIVE, "启动"),
    (ACCOUNT_STATUS_LOCKED, "锁定"),
    (ACCOUNT_STATUS_RESIGNED, "离职"),
]
ACCOUNT_STATUS_CODES = {code for code, _ in ACCOUNT_STATUSES}
ACCOUNT_STATUS_LABELS = {code: label for code, label in ACCOUNT_STATUSES}


def account_status_label(code: Optional[str]) -> str:
    return ACCOUNT_STATUS_LABELS.get(code or "", code or "")


def normalize_account_status(code: Optional[str], is_active: Optional[bool] = None) -> str:
    if code in ACCOUNT_STATUS_CODES:
        return code  # type: ignore[return-value]
    if is_active is False:
        return ACCOUNT_STATUS_LOCKED
    return ACCOUNT_STATUS_ACTIVE


def enrich_user_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    status = normalize_account_status(item.get("account_status"), bool(item.get("is_active", True)))
    item["account_status"] = status
    item["account_status_label"] = account_status_label(status)
    item["is_active"] = status == ACCOUNT_STATUS_ACTIVE
    return item



def case_status_label(code: Optional[str]) -> str:
    if not code:
        return CASE_STATUS_LABELS[CASE_STATUS_INIT]
    return CASE_STATUS_LABELS.get(code, code)


def enrich_case(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["status_label"] = case_status_label(item.get("status"))
    meta: Dict[str, Any] = {}
    raw = item.get("meta_json")
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                meta = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            meta = {}
    item["meta"] = meta
    item["contract_file_ids"] = list(meta.get("contract_file_ids") or [])
    item["evidence_file_ids"] = list(meta.get("evidence_file_ids") or [])
    case_type = meta.get("case_type")
    if case_type not in CASE_TYPE_CODES:
        case_type = None
    item["case_type"] = case_type
    item["case_type_label"] = CASE_TYPE_LABELS.get(case_type or "", "") if case_type else ""
    return item


class RbacStore:
    def __init__(self, db_path: str = "./rbac.db"):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def ensure_schema(self) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                account_status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                is_system INTEGER NOT NULL DEFAULT 0,
                track TEXT NOT NULL,
                description TEXT
            );
            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                group_name TEXT,
                description TEXT
            );
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id INTEGER NOT NULL,
                permission_id INTEGER NOT NULL,
                PRIMARY KEY (role_id, permission_id),
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_no TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'init',
                created_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                meta_json TEXT,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS case_members (
                user_id INTEGER NOT NULL,
                case_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                assigned_by INTEGER,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (user_id, case_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id),
                FOREIGN KEY (assigned_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                client_type TEXT NOT NULL,
                id_number TEXT NOT NULL UNIQUE,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS case_clients (
                case_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                PRIMARY KEY (case_id, client_id),
                FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );
            """
        )
        try:
            cur.execute(
                "UPDATE cases SET status = 'init' WHERE status IN ('open', '') OR status IS NULL"
            )
        except sqlite3.OperationalError:
            pass
        self._ensure_user_account_status_column(cur)
        conn.commit()
        conn.close()

    def _ensure_user_account_status_column(self, cur: sqlite3.Cursor) -> None:
        cols = {r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()}
        if "account_status" not in cols:
            cur.execute(
                "ALTER TABLE users ADD COLUMN account_status TEXT NOT NULL DEFAULT 'active'"
            )
            cur.execute(
                "UPDATE users SET account_status = 'active' WHERE is_active = 1 OR is_active IS NULL"
            )
            cur.execute(
                "UPDATE users SET account_status = 'locked' WHERE is_active = 0"
            )

    def seed_defaults(self) -> None:
        conn = self._connect()
        cur = conn.cursor()
        now = datetime.now().isoformat()

        for role in SYSTEM_ROLES:
            cur.execute(
                "INSERT OR IGNORE INTO roles (code, name, is_system, track, description) VALUES (?, ?, 1, ?, ?)",
                (role["code"], role["name"], role["track"], role["description"]),
            )

        for code, name, kind, group_name in PERMISSIONS:
            cur.execute(
                "INSERT OR IGNORE INTO permissions (code, name, kind, group_name, description) VALUES (?, ?, ?, ?, ?)",
                (code, name, kind, group_name, name),
            )

        for role_code, perm_codes in DEFAULT_ROLE_PERMS.items():
            cur.execute("SELECT id FROM roles WHERE code = ?", (role_code,))
            role_row = cur.fetchone()
            if not role_row:
                continue
            role_id = role_row["id"]
            for pcode in perm_codes:
                cur.execute("SELECT id FROM permissions WHERE code = ?", (pcode,))
                prow = cur.fetchone()
                if prow:
                    cur.execute(
                        "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                        (role_id, prow["id"]),
                    )

        cur.execute("SELECT id FROM users WHERE username = ?", ("director",))
        if not cur.fetchone():
            cur.execute(
                """
                INSERT INTO users (
                    username, password_hash, display_name, is_active,
                    must_change_password, created_at, account_status
                )
                VALUES (?, ?, ?, 1, 1, ?, 'active')
                """,
                ("director", "!unset", "律所主任", now),
            )
            cur.execute("SELECT id FROM users WHERE username = ?", ("director",))
            user_id = cur.fetchone()["id"]
            cur.execute("SELECT id FROM roles WHERE code = ?", ("director",))
            role_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role_id),
            )

        conn.commit()
        conn.close()

    def list_roles(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, code, name, is_system, track, description FROM roles ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_role_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT id, code, name, is_system, track, description FROM roles WHERE code = ?",
            (code,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def list_permissions(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, code, name, kind, group_name, description FROM permissions ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def permissions_for_role_codes(self, codes: List[str]) -> Set[str]:
        if not codes:
            return set()
        conn = self._connect()
        placeholders = ",".join("?" * len(codes))
        rows = conn.execute(
            f"""
            SELECT DISTINCT p.code
            FROM permissions p
            JOIN role_permissions rp ON rp.permission_id = p.id
            JOIN roles r ON r.id = rp.role_id
            WHERE r.code IN ({placeholders})
            """,
            tuple(codes),
        ).fetchall()
        conn.close()
        return {r["code"] for r in rows}

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT id, username, password_hash, display_name, is_active,
                   must_change_password, created_at, account_status
            FROM users WHERE username = ?
            """,
            (username,),
        ).fetchone()
        conn.close()
        return enrich_user_row(dict(row)) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT id, username, password_hash, display_name, is_active,
                   must_change_password, created_at, account_status
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        conn.close()
        return enrich_user_row(dict(row)) if row else None

    def update_password_hash(self, user_id: int, password_hash: str, must_change: Optional[bool] = None) -> None:
        conn = self._connect()
        if must_change is None:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
                (password_hash, 1 if must_change else 0, user_id),
            )
        conn.commit()
        conn.close()

    def create_user(
        self,
        username: str,
        password_hash: str,
        display_name: str = "",
        must_change_password: bool = True,
        is_active: bool = True,
        account_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        status = normalize_account_status(
            account_status,
            is_active if account_status is None else (account_status == ACCOUNT_STATUS_ACTIVE),
        )
        now = datetime.now().isoformat()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (
                username, password_hash, display_name, is_active,
                must_change_password, created_at, account_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                password_hash,
                display_name or username,
                1 if status == ACCOUNT_STATUS_ACTIVE else 0,
                1 if must_change_password else 0,
                now,
                status,
            ),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return self.get_user_by_id(user_id)  # type: ignore

    def update_user_profile(
        self,
        user_id: int,
        display_name: Optional[str] = None,
        account_status: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> None:
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("user not found")
        name = display_name if display_name is not None else user.get("display_name")
        if account_status is not None:
            status = normalize_account_status(account_status)
        elif is_active is not None:
            status = ACCOUNT_STATUS_ACTIVE if is_active else ACCOUNT_STATUS_LOCKED
        else:
            status = user.get("account_status") or ACCOUNT_STATUS_ACTIVE
        if status not in ACCOUNT_STATUS_CODES:
            raise ValueError(f"invalid account status: {status}")
        conn = self._connect()
        conn.execute(
            """
            UPDATE users SET display_name = ?, account_status = ?, is_active = ?
            WHERE id = ?
            """,
            (name, status, 1 if status == ACCOUNT_STATUS_ACTIVE else 0, user_id),
        )
        conn.commit()
        conn.close()

    def set_user_roles(self, user_id: int, role_codes: List[str]) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for code in role_codes:
            cur.execute("SELECT id FROM roles WHERE code = ?", (code,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"unknown role: {code}")
            cur.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, row["id"]),
            )
        conn.commit()
        conn.close()

    def list_user_role_codes(self, user_id: int) -> List[str]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT r.code FROM roles r
            JOIN user_roles ur ON ur.role_id = r.id
            WHERE ur.user_id = ?
            ORDER BY r.id
            """,
            (user_id,),
        ).fetchall()
        conn.close()
        return [r["code"] for r in rows]

    def set_role_permissions(self, role_code: str, perm_codes: List[str]) -> None:
        role = self.get_role_by_code(role_code)
        if not role:
            raise ValueError(f"unknown role: {role_code}")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM role_permissions WHERE role_id = ?", (role["id"],))
        for code in perm_codes:
            cur.execute("SELECT id FROM permissions WHERE code = ?", (code,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"unknown permission: {code}")
            cur.execute(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                (role["id"], row["id"]),
            )
        conn.commit()
        conn.close()

    def create_session(self, token: str, user_id: int, expires_at: str) -> None:
        now = datetime.now().isoformat()
        conn = self._connect()
        conn.execute(
            "INSERT INTO auth_sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expires_at, now),
        )
        conn.commit()
        conn.close()

    def delete_session(self, token: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT token, user_id, expires_at, created_at FROM auth_sessions WHERE token = ?",
            (token,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT id, username, display_name, is_active, must_change_password, created_at, account_status
            FROM users ORDER BY id
            """
        ).fetchall()
        conn.close()
        return [enrich_user_row(dict(r)) for r in rows]

    def set_user_active(self, user_id: int, is_active: bool) -> None:
        self.update_user_profile(user_id, is_active=is_active)

    def set_user_account_status(self, user_id: int, account_status: str) -> None:
        self.update_user_profile(user_id, account_status=account_status)

    def update_permission_meta(
        self,
        code: str,
        name: Optional[str] = None,
        group_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM permissions WHERE code = ?", (code,)).fetchone()
        if not row:
            conn.close()
            return None
        new_name = name if name is not None else row["name"]
        new_group = group_name if group_name is not None else row["group_name"]
        new_desc = description if description is not None else row["description"]
        conn.execute(
            "UPDATE permissions SET name = ?, group_name = ?, description = ? WHERE code = ?",
            (new_name, new_group, new_desc, code),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT id, code, name, kind, group_name, description FROM permissions WHERE code = ?",
            (code,),
        ).fetchone()
        conn.close()
        return dict(updated) if updated else None

    def list_role_permission_codes(self, role_code: str) -> List[str]:
        return sorted(self.permissions_for_role_codes([role_code]))

    def next_case_no(self, case_type: str, when: Optional[datetime] = None) -> str:
        """按「年份+类型缩写+流水号」生成案号，如 2026民0001。"""
        if case_type not in CASE_TYPE_CODES:
            raise ValueError(f"invalid case type: {case_type}")
        abbr = CASE_TYPE_ABBR[case_type]
        year = (when or datetime.now()).year
        prefix = f"{year}{abbr}"
        conn = self._connect()
        rows = conn.execute(
            "SELECT case_no FROM cases WHERE case_no LIKE ?",
            (prefix + "%",),
        ).fetchall()
        conn.close()
        max_seq = 0
        for row in rows:
            no = row["case_no"] or ""
            if not no.startswith(prefix):
                continue
            suffix = no[len(prefix):]
            if suffix.isdigit():
                max_seq = max(max_seq, int(suffix))
        return f"{prefix}{max_seq + 1:04d}"

    def create_case(
        self,
        case_no: str,
        title: str,
        created_by: Optional[int] = None,
        status: str = CASE_STATUS_INIT,
        meta_json: Optional[str] = None,
    ) -> Dict[str, Any]:
        if status not in CASE_STATUS_CODES:
            raise ValueError(f"invalid case status: {status}")
        now = datetime.now().isoformat()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cases (case_no, title, status, created_by, created_at, updated_at, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (case_no, title, status, created_by, now, now, meta_json),
        )
        conn.commit()
        case_id = cur.lastrowid
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        conn.close()
        return enrich_case(dict(row))

    def get_case(self, case_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        conn.close()
        return enrich_case(dict(row)) if row else None

    def list_cases(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM cases ORDER BY id DESC").fetchall()
        conn.close()
        return [enrich_case(dict(r)) for r in rows]

    def list_cases_for_user(self, user_id: int, all_cases: bool = False) -> List[Dict[str, Any]]:
        if all_cases:
            return self.list_cases()
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT c.* FROM cases c
            JOIN case_members m ON m.case_id = c.id
            WHERE m.user_id = ?
            ORDER BY c.id DESC
            """,
            (user_id,),
        ).fetchall()
        conn.close()
        return [enrich_case(dict(r)) for r in rows]

    def update_case(
        self,
        case_id: int,
        title: Optional[str] = None,
        status: Optional[str] = None,
        case_no: Optional[str] = None,
        meta_json: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        case = self.get_case(case_id)
        if not case:
            return None
        if status is not None and status not in CASE_STATUS_CODES:
            raise ValueError(f"invalid case status: {status}")
        now = datetime.now().isoformat()
        conn = self._connect()
        if meta_json is not None:
            conn.execute(
                """
                UPDATE cases SET title = ?, status = ?, case_no = ?, meta_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    title if title is not None else case["title"],
                    status if status is not None else case["status"],
                    case_no if case_no is not None else case["case_no"],
                    meta_json,
                    now,
                    case_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE cases SET title = ?, status = ?, case_no = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    title if title is not None else case["title"],
                    status if status is not None else case["status"],
                    case_no if case_no is not None else case["case_no"],
                    now,
                    case_id,
                ),
            )
        conn.commit()
        conn.close()
        return self.get_case(case_id)

    def delete_case(self, case_id: int) -> bool:
        if not self.get_case(case_id):
            return False
        conn = self._connect()
        conn.execute("DELETE FROM case_clients WHERE case_id = ?", (case_id,))
        conn.execute("DELETE FROM case_members WHERE case_id = ?", (case_id,))
        cur = conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        conn.commit()
        deleted = cur.rowcount > 0
        conn.close()
        return deleted

    def set_case_clients(self, case_id: int, client_ids: List[int]) -> List[Dict[str, Any]]:
        if not self.get_case(case_id):
            raise ValueError("案件不存在")
        unique_ids: List[int] = []
        seen = set()
        for raw in client_ids or []:
            cid = int(raw)
            if cid in seen:
                continue
            seen.add(cid)
            if not self.get_client(cid):
                raise ValueError(f"客户不存在: {cid}")
            unique_ids.append(cid)
        conn = self._connect()
        conn.execute("DELETE FROM case_clients WHERE case_id = ?", (case_id,))
        for cid in unique_ids:
            conn.execute(
                "INSERT INTO case_clients (case_id, client_id) VALUES (?, ?)",
                (case_id, cid),
            )
        conn.commit()
        conn.close()
        return self.list_case_clients(case_id)

    def list_case_clients(self, case_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT c.id, c.name, c.client_type, c.id_number, c.created_by, c.created_at, c.updated_at
            FROM clients c
            JOIN case_clients cc ON cc.client_id = c.id
            WHERE cc.case_id = ?
            ORDER BY c.id
            """,
            (case_id,),
        ).fetchall()
        conn.close()
        return [enrich_client(dict(r)) for r in rows]

    def add_case_member(
        self,
        case_id: int,
        user_id: int,
        role_code: str,
        assigned_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("user not found")
        firm_roles = set(self.list_user_role_codes(user_id))
        if firm_roles & FIRM_TRACK_ROLES:
            raise ValueError("director/admin_officer cannot be case members")
        if role_code not in CASE_TRACK_ROLES:
            raise ValueError("case member role must be partner, lead_lawyer, or assistant")
        role = self.get_role_by_code(role_code)
        if not role:
            raise ValueError(f"unknown role: {role_code}")
        if not self.get_case(case_id):
            raise ValueError("case not found")
        now = datetime.now().isoformat()
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO case_members (user_id, case_id, role_id, assigned_by, assigned_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, case_id) DO UPDATE SET
              role_id = excluded.role_id,
              assigned_by = excluded.assigned_by,
              assigned_at = excluded.assigned_at
            """,
            (user_id, case_id, role["id"], assigned_by, now),
        )
        conn.commit()
        conn.close()
        return self.get_case_member(case_id, user_id)  # type: ignore

    def remove_case_member(self, case_id: int, user_id: int) -> None:
        conn = self._connect()
        conn.execute(
            "DELETE FROM case_members WHERE case_id = ? AND user_id = ?",
            (case_id, user_id),
        )
        conn.commit()
        conn.close()

    def get_case_member(self, case_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT m.user_id, m.case_id, m.assigned_by, m.assigned_at,
                   r.code AS role_code, r.name AS role_name,
                   u.username, u.display_name
            FROM case_members m
            JOIN roles r ON r.id = m.role_id
            JOIN users u ON u.id = m.user_id
            WHERE m.case_id = ? AND m.user_id = ?
            """,
            (case_id, user_id),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def list_case_members(self, case_id: int) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT m.user_id, m.case_id, m.assigned_by, m.assigned_at,
                   r.code AS role_code, r.name AS role_name,
                   u.username, u.display_name
            FROM case_members m
            JOIN roles r ON r.id = m.role_id
            JOIN users u ON u.id = m.user_id
            WHERE m.case_id = ?
            ORDER BY m.assigned_at
            """,
            (case_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def case_role_code(self, user_id: int, case_id: int) -> Optional[str]:
        member = self.get_case_member(case_id, user_id)
        return member["role_code"] if member else None

    def list_clients(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT id, name, client_type, id_number, created_by, created_at, updated_at
            FROM clients ORDER BY id DESC
            """
        ).fetchall()
        conn.close()
        return [enrich_client(dict(r)) for r in rows]

    def get_client(self, client_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT id, name, client_type, id_number, created_by, created_at, updated_at
            FROM clients WHERE id = ?
            """,
            (client_id,),
        ).fetchone()
        conn.close()
        return enrich_client(dict(row)) if row else None

    def get_client_by_id_number(self, id_number: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT id, name, client_type, id_number, created_by, created_at, updated_at
            FROM clients WHERE id_number = ?
            """,
            (id_number,),
        ).fetchone()
        conn.close()
        return enrich_client(dict(row)) if row else None

    def create_client(
        self,
        name: str,
        client_type: str,
        id_number: str,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        if client_type not in CLIENT_TYPE_CODES:
            raise ValueError("客户类型须为个人或企业")
        name = (name or "").strip()
        if not name:
            raise ValueError("名称必填")
        id_number = validate_client_id_number(client_type, id_number)
        if self.get_client_by_id_number(id_number):
            raise ValueError("识别号已存在")
        now = datetime.now().isoformat()
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO clients (name, client_type, id_number, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, client_type, id_number, created_by, now, now),
            )
            conn.commit()
            client_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            conn.close()
            raise ValueError("识别号已存在") from exc
        conn.close()
        return self.get_client(client_id)  # type: ignore

    def update_client(
        self,
        client_id: int,
        name: Optional[str] = None,
        client_type: Optional[str] = None,
        id_number: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        client = self.get_client(client_id)
        if not client:
            return None
        new_name = name.strip() if isinstance(name, str) else client["name"]
        new_type = client_type if client_type is not None else client["client_type"]
        raw_id = id_number.strip() if isinstance(id_number, str) else client["id_number"]
        if new_type not in CLIENT_TYPE_CODES:
            raise ValueError("客户类型须为个人或企业")
        if not new_name:
            raise ValueError("名称必填")
        new_id = validate_client_id_number(new_type, raw_id)
        other = self.get_client_by_id_number(new_id)
        if other and other["id"] != client_id:
            raise ValueError("识别号已存在")
        now = datetime.now().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE clients SET name = ?, client_type = ?, id_number = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_name, new_type, new_id, now, client_id),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.close()
            raise ValueError("识别号已存在") from exc
        conn.close()
        return self.get_client(client_id)

    def delete_client(self, client_id: int) -> bool:
        conn = self._connect()
        cur = conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        conn.commit()
        deleted = cur.rowcount > 0
        conn.close()
        return deleted
