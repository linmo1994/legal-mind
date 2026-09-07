#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from orchestrate_sse_util import sse_data_line  # noqa: E402


class TestOrchestrateSse(unittest.TestCase):
    def test_sse_error_line(self):
        b = sse_data_line({"type": "error", "error": "任务编排失败", "detail": "x"})
        self.assertTrue(b.startswith(b"data: "))
        self.assertIn(b"error", b)


if __name__ == "__main__":
    unittest.main()
