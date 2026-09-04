"""Password hashing and session tokens for LegalMind RBAC."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from rbac_store import RbacStore

PBKDF2_ITERATIONS = 200_000
DEFAULT_SESSION_DAYS = 7
SEED_USERNAME = "director"
SEED_PASSWORD = "ChangeMe123!"


class AuthService:
    def __init__(self, store: RbacStore, session_days: int = DEFAULT_SESSION_DAYS):
        self.store = store
        self.session_days = session_days

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
        )
        return f"pbkdf2${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            algo, iters_s, salt_hex, hash_hex = password_hash.split("$", 3)
            if algo != "pbkdf2":
                return False
            iterations = int(iters_s)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, iterations
            )
            return hmac.compare_digest(digest, expected)
        except (ValueError, TypeError):
            return False

    def ensure_seed_director(self, password: str = SEED_PASSWORD) -> None:
        user = self.store.get_user_by_username(SEED_USERNAME)
        if not user:
            self.store.seed_defaults()
            user = self.store.get_user_by_username(SEED_USERNAME)
        if not user:
            raise RuntimeError("seed director user missing")
        if not user["password_hash"] or user["password_hash"] == "!unset":
            self.store.update_password_hash(
                user["id"], self.hash_password(password), must_change=True
            )
        roles = self.store.list_user_role_codes(user["id"])
        if "director" not in roles:
            self.store.set_user_roles(user["id"], ["director"])

    def login(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        user = self.store.get_user_by_username(username)
        if not user or not user.get("is_active"):
            return None
        if not self.verify_password(password, user["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        expires = (datetime.now() + timedelta(days=self.session_days)).isoformat()
        self.store.create_session(token, user["id"], expires)
        firm_roles = self.store.list_user_role_codes(user["id"])
        firm_permissions = sorted(self.store.permissions_for_role_codes(firm_roles))
        return {
            "token": token,
            "user": self._public_user(user),
            "firm_roles": firm_roles,
            "firm_permissions": firm_permissions,
        }

    def logout(self, token: str) -> None:
        if token:
            self.store.delete_session(token)

    def resolve_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        session = self.store.get_session(token)
        if not session:
            return None
        try:
            expires = datetime.fromisoformat(session["expires_at"])
        except ValueError:
            self.store.delete_session(token)
            return None
        if expires < datetime.now():
            self.store.delete_session(token)
            return None
        user = self.store.get_user_by_id(session["user_id"])
        if not user or not user.get("is_active"):
            return None
        return self._public_user(user)

    def firm_roles_and_permissions(self, user_id: int) -> Dict[str, List[str]]:
        roles = self.store.list_user_role_codes(user_id)
        perms = sorted(self.store.permissions_for_role_codes(roles))
        return {"firm_roles": roles, "firm_permissions": perms}

    @staticmethod
    def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "is_active": bool(user.get("is_active")),
            "account_status": user.get("account_status") or "active",
            "account_status_label": user.get("account_status_label") or "启动",
            "must_change_password": bool(user.get("must_change_password")),
        }
