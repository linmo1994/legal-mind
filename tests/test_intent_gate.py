#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents.intent_gate import (  # noqa: E402
    classify_domain_intent,
    parse_gate_payload,
)


class TestIntentGate(unittest.TestCase):
    def test_parse_non_legal(self):
        self.assertEqual(parse_gate_payload('{"domain":"non_legal"}')["domain"], "non_legal")

    def test_parse_legal_intent(self):
        p = parse_gate_payload('思考\n{"domain":"legal","intent":"law_search"}')
        self.assertEqual(p["intent"], "law_search")

    def test_parse_invalid_intent(self):
        self.assertIsNone(parse_gate_payload('{"domain":"legal","intent":"foo"}'))

    def test_classify_calls_llm_once(self):
        calls = []

        def llm(system, user, hist=None):
            calls.append(1)
            return '{"domain":"non_legal"}'

        out = classify_domain_intent(llm, "今天天气怎么样")
        self.assertEqual(out["domain"], "non_legal")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
