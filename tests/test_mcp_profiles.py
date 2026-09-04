#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from config_admin import create_profile, delete_profile, list_public_profiles, update_profile  # noqa: E402


BASE = {
    "mcp_server": {"host": "localhost", "port": 8001},
    "llm": {
        "api_url": "https://api.deepseek.com/v1/chat/completions",
        "api_key": "sk-secret",
        "model": "deepseek-chat",
        "timeout": 1000,
        "max_retries": 1,
        "temperature": 0,
        "max_tokens": 100,
    },
}


class TestProfiles(unittest.TestCase):
    def test_synthesize_and_create_mcp(self):
        listed = list_public_profiles(BASE)
        self.assertEqual(len(listed["mcp_profiles"]), 1)
        cfg, item = create_profile(BASE, {
            "kind": "mcp",
            "name": "备用",
            "host": "127.0.0.1",
            "port": 9000,
        })
        self.assertEqual(item["port"], 9000)
        self.assertEqual(len(cfg["mcp_profiles"]), 2)
        self.assertNotIn("api_key", item)

    def test_cannot_delete_last(self):
        cfg, extra = create_profile(BASE, {"kind": "mcp", "name": "backup", "host": "h", "port": 9})
        cfg = delete_profile(cfg, "mcp", extra["id"])
        with self.assertRaises(ValueError):
            delete_profile(cfg, "mcp", cfg["mcp_profiles"][0]["id"])

    def test_activate_llm_updates_root(self):
        cfg, created = create_profile(BASE, {
            "kind": "llm",
            "name": "备用模型",
            "api_url": "https://example.com/v1",
            "model": "other",
            "timeout": 10,
            "max_retries": 1,
            "temperature": 0.2,
            "max_tokens": 50,
            "active": True,
        })
        self.assertTrue(created["active"])
        self.assertEqual(cfg["llm"]["model"], "other")
        cfg, updated = update_profile(cfg, "llm", "default", {"active": True, "model": "deepseek-chat"})
        self.assertTrue(updated["active"])
        self.assertEqual(cfg["llm"]["model"], "deepseek-chat")


if __name__ == "__main__":
    unittest.main()
