# tests/test_case_stages.py
import unittest
from rbac_store import (
    CASE_STAGE_CODES,
    CASE_STAGE_ORDER,
    next_stage,
    can_transition_stage,
)

class TestCaseStages(unittest.TestCase):
    def test_five_stages_ordered(self):
        self.assertEqual(
            CASE_STAGE_ORDER,
            ["intake", "materials_ready", "strategy_docs", "litigation", "closed"],
        )
        self.assertTrue(can_transition_stage("intake", "materials_ready"))
        self.assertFalse(can_transition_stage("intake", "closed"))
        self.assertEqual(next_stage("intake"), "materials_ready")
        self.assertIsNone(next_stage("closed"))
