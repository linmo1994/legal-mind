#!/usr/bin/env python3
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from http_api_extra import admin_overview_stats  # noqa: E402


class TestAdminStats(unittest.TestCase):
    @patch("http_api_extra.load_full_config")
    def test_mcp_counts_services_not_tools(self, load_cfg):
        load_cfg.return_value = {
            "mcp_server": {"host": "127.0.0.1", "port": 8001},
            "mcp_profiles": [
                {"id": "a", "name": "本机", "host": "127.0.0.1", "port": 8001, "active": True},
            ],
            "llm_profiles": [{"id": "l", "name": "m", "active": True}],
        }
        mcp = MagicMock()
        mcp.vector_service.count_documents.return_value = {
            "document_count": 4,
            "chunk_count": 12,
        }
        mcp.rbac_store.list_users.return_value = [{"id": 1}, {"id": 2}]
        mcp.rbac_store.list_cases.return_value = [{"id": 1}]
        mcp.rbac_store.list_roles.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]
        mcp.rbac_store.list_permissions.return_value = [{"id": 1}] * 5
        out = admin_overview_stats(mcp)
        self.assertEqual(out["mcp_service_count"], 1)
        self.assertNotIn("mcp_tool_count", out)
        self.assertEqual(out["document_count"], 4)
        self.assertEqual(out["chunk_count"], 12)
        self.assertGreaterEqual(out["skill_count"], 0)
        self.assertEqual(out["user_count"], 2)
        self.assertEqual(out["case_count"], 1)
        self.assertEqual(out["role_count"], 3)
        self.assertEqual(out["permission_count"], 5)

    @patch("http_api_extra.load_full_config")
    def test_vector_missing(self, load_cfg):
        load_cfg.return_value = {
            "mcp_profiles": [
                {"id": "a", "active": True},
                {"id": "b", "active": False},
            ],
            "llm_profiles": [{"id": "l", "active": True}],
        }
        mcp = MagicMock()
        mcp.vector_service = None
        mcp._vector_service_instance = None
        mcp.rbac_store = None
        out = admin_overview_stats(mcp)
        self.assertEqual(out["mcp_service_count"], 2)
        self.assertEqual(out["document_count"], 0)
        self.assertEqual(out["vector_error"], "向量服务未就绪")
        self.assertEqual(out["user_count"], 0)
        self.assertEqual(out["case_count"], 0)


if __name__ == "__main__":
    unittest.main()
