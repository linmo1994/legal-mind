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
