"""SQLite persistence for RBAC, auth sessions, and cases."""

from __future__ import annotations

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
                created_at TEXT NOT NULL
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
                status TEXT NOT NULL DEFAULT 'open',
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
            """
        )
        conn.commit()
        conn.close()

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
            cur.execute("SELECT COUNT(*) AS c FROM role_permissions WHERE role_id = ?", (role_id,))
            if cur.fetchone()["c"] > 0:
                continue
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
                INSERT INTO users (username, password_hash, display_name, is_active, must_change_password, created_at)
                VALUES (?, ?, ?, 1, 1, ?)
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
                   must_change_password, created_at
            FROM users WHERE username = ?
            """,
            (username,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT id, username, password_hash, display_name, is_active,
                   must_change_password, created_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

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
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, password_hash, display_name, is_active, must_change_password, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                password_hash,
                display_name or username,
                1 if is_active else 0,
                1 if must_change_password else 0,
                now,
            ),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return self.get_user_by_id(user_id)  # type: ignore

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
            SELECT id, username, display_name, is_active, must_change_password, created_at
            FROM users ORDER BY id
            """
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def set_user_active(self, user_id: int, is_active: bool) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
        conn.commit()
        conn.close()

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

    def create_case(
        self,
        case_no: str,
        title: str,
        created_by: Optional[int] = None,
        status: str = "open",
        meta_json: Optional[str] = None,
    ) -> Dict[str, Any]:
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
        return dict(row)

    def get_case(self, case_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def list_cases(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM cases ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

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
        return [dict(r) for r in rows]

    def update_case(
        self,
        case_id: int,
        title: Optional[str] = None,
        status: Optional[str] = None,
        case_no: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        case = self.get_case(case_id)
        if not case:
            return None
        now = datetime.now().isoformat()
        conn = self._connect()
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
