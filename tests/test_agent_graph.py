#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents.graph import OrchestrationError, validate_subcall  # noqa: E402


class TestAgentGraph(unittest.TestCase):
    def test_analysis_may_call_retrieval_at_depth_1(self):
        validate_subcall("text_analysis", "legal_retrieval", depth=1, visited={"text_analysis"})

    def test_retrieval_cannot_call_analysis(self):
        with self.assertRaises(OrchestrationError):
            validate_subcall("legal_retrieval", "text_analysis", depth=1, visited={"legal_retrieval"})

    def test_cycle_rejected(self):
        with self.assertRaises(OrchestrationError):
            validate_subcall(
                "text_analysis",
                "legal_retrieval",
                depth=1,
                visited={"legal_retrieval", "text_analysis"},
            )

    def test_depth_greater_than_2_rejected(self):
        with self.assertRaises(OrchestrationError):
            validate_subcall("text_analysis", "legal_retrieval", depth=2, visited={"text_analysis"})

    def test_writer_may_call_analysis(self):
        validate_subcall("doc_writing", "text_analysis", depth=1, visited={"doc_writing"})

    def test_cannot_call_orchestrator(self):
        with self.assertRaises(OrchestrationError):
            validate_subcall("text_analysis", "orchestrator", depth=1, visited={"text_analysis"})


if __name__ == "__main__":
    unittest.main()
