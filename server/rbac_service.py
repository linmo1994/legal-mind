"""Resolve firm-level and case-scoped permissions."""

from __future__ import annotations

from typing import Optional, Set

from rbac_store import RbacStore


class RbacService:
    def __init__(self, store: RbacStore):
        self.store = store

    def firm_permissions(self, user_id: int) -> Set[str]:
        roles = self.store.list_user_role_codes(user_id)
        return self.store.permissions_for_role_codes(roles)

    def case_permissions(self, user_id: int, case_id: int) -> Set[str]:
        role_code = self.store.case_role_code(user_id, case_id)
        if not role_code:
            return set()
        return self.store.permissions_for_role_codes([role_code])

    def effective_permissions(self, user_id: int, case_id: Optional[int] = None) -> Set[str]:
        perms = set(self.firm_permissions(user_id))
        if case_id is not None:
            perms |= self.case_permissions(user_id, case_id)
        return perms

    def require(self, user_id: int, perm: str, case_id: Optional[int] = None) -> bool:
        return perm in self.effective_permissions(user_id, case_id)
