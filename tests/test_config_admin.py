#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from config_admin import redact_llm_config, validate_mcp_config_update  # noqa: E402


class TestConfigAdmin(unittest.TestCase):
    def test_redact_key(self):
        out = redact_llm_config({
            "api_url": "https://api.deepseek.com/v1/chat/completions",
            "api_key": "sk-secret-value",
            "model": "deepseek-chat",
        })
        self.assertEqual(out["api_key_set"], True)
        self.assertNotIn("sk-secret", str(out.get("api_key", "")))
        self.assertEqual(out["model"], "deepseek-chat")

    def test_port_must_be_int(self):
        with self.assertRaises(ValueError):
            validate_mcp_config_update({"mcp_server": {"host": "localhost", "port": "abc"}})

    def test_api_url_must_be_http(self):
        with self.assertRaises(ValueError):
            validate_mcp_config_update({"llm": {"api_url": "ftp://x"}})

    def test_valid_update(self):
        data = validate_mcp_config_update({
            "mcp_server": {"host": "127.0.0.1", "port": 8001},
            "llm": {"api_url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"},
        })
        self.assertEqual(data["mcp_server"]["port"], 8001)


if __name__ == "__main__":
    unittest.main()
