# tests/test_case_materials.py
import unittest
from unittest.mock import MagicMock

from case_materials import (
    _heuristic_brief,
    allow_case_material_access,
    build_case_material_context,
    ensure_evidence_briefs,
    generate_evidence_brief,
    get_case_evidence_text,
    parse_evidence_tool_call,
    resolve_cases_for_file_id,
    truncate_chars,
    EVIDENCE_BRIEF_MAX,
)


class TestCaseMaterials(unittest.TestCase):
    def test_truncate(self):
        self.assertEqual(truncate_chars("abcd", 3), "abc…[已截断]")

    def test_evidence_brief_capped_at_max(self):
        long_text = "证" * 500
        brief = _heuristic_brief(long_text)
        self.assertLessEqual(len(brief), EVIDENCE_BRIEF_MAX)
        self.assertTrue(brief.endswith("…"))

        def write_llm(system, user, hist=None):
            return "说" * 300

        llm_brief = generate_evidence_brief("正文", write_llm=write_llm)
        self.assertLessEqual(len(llm_brief), EVIDENCE_BRIEF_MAX)

    def test_build_includes_contract_and_evidence_brief(self):
        store = MagicMock()
        store.get_case.return_value = {
            "id": 1,
            "case_no": "A1",
            "title": "借贷",
            "meta": {
                "case_type": "civil",
                "contract_file_ids": ["c1"],
                "evidence_file_ids": ["e1"],
            },
        }
        fs = MagicMock()
        def get_file(fid):
            if fid == "c1":
                return {"file_id": "c1", "original_name": "委托.pdf", "file_type": "pdf",
                        "text_content": "合同正文" * 10, "metadata": {}}
            return {"file_id": "e1", "original_name": "转账.png", "file_type": "png",
                    "text_content": "长正文", "metadata": {"evidence_brief": "银行转账截图摘要"}}
        fs.get_file.side_effect = get_file
        fs.get_file_text.side_effect = lambda fid: get_file(fid).get("text_content")
        text = build_case_material_context(1, store, fs)
        self.assertIn("【委托合同】", text)
        self.assertIn("合同正文", text)
        self.assertIn("转账.png", text)
        self.assertIn("银行转账截图摘要", text)
        self.assertNotIn("长正文", text)

    def test_get_evidence_rejects_non_case_file(self):
        store = MagicMock()
        store.get_case.return_value = {"id": 1, "meta": {"evidence_file_ids": ["e1"]}}
        fs = MagicMock()
        with self.assertRaises(ValueError):
            get_case_evidence_text(1, "e99", store, fs)

    def test_parse_tool_call(self):
        raw = '需要看全文\n{"tool":"get_case_evidence_file","file_id":"e1"}\n'
        self.assertEqual(parse_evidence_tool_call(raw), "e1")
        self.assertIsNone(parse_evidence_tool_call("普通回答"))

    def test_ensure_brief_writes_metadata(self):
        fs = MagicMock()
        fs.get_file.return_value = {
            "file_id": "e1", "text_content": "证据全文内容足够长", "metadata": {}, "description": None
        }
        def write_llm(system, user, hist=None):
            return "这是一份不超过二百字的说明。"
        ensure_evidence_briefs(fs, ["e1"], write_llm=write_llm)
        fs.update_file_metadata.assert_called()
        args = fs.update_file_metadata.call_args
        self.assertEqual(args[0][0], "e1")
        self.assertIn("evidence_brief", args[0][1])
        self.assertLessEqual(len(args[0][1]["evidence_brief"]), EVIDENCE_BRIEF_MAX)

    def test_resolve_cases_matches_evidence_only_not_contract(self):
        store = MagicMock()

        def get_case(cid):
            cases = {
                1: {"id": 1, "meta": {"evidence_file_ids": ["e1"], "contract_file_ids": []}},
                2: {"id": 2, "meta": {"evidence_file_ids": [], "contract_file_ids": ["e1"]}},
            }
            return cases.get(int(cid))

        store.get_case.side_effect = get_case
        self.assertEqual(resolve_cases_for_file_id("e1", [1, 2], store), [1])

    def test_allow_case_material_access_deny_skips_build(self):
        """Unauthorized case_id must not reach build_case_material_context."""
        api = MagicMock()
        api.check_orchestrate_access.return_value = (403, {"error": "无权限：cap.chat"})
        self.assertFalse(allow_case_material_access("Bearer x", 1, api))
        api.check_orchestrate_access.assert_called_once_with(
            "Bearer x", {"case_id": 1, "user_text": ""}
        )

        # Mirror llm_proxy gate: only build when access OK
        store = MagicMock()
        fs = MagicMock()
        built = None
        if allow_case_material_access("Bearer x", 1, api):
            built = build_case_material_context(1, store, fs)
        self.assertIsNone(built)
        store.get_case.assert_not_called()

    def test_allow_case_material_access_ok_and_no_case(self):
        api = MagicMock()
        api.check_orchestrate_access.return_value = (
            200,
            {"user": {"id": 1}, "case_id": 7},
        )
        self.assertTrue(allow_case_material_access("Bearer t", 7, api))
        self.assertFalse(allow_case_material_access(None, None, api))
        self.assertFalse(allow_case_material_access(None, "", api))
        self.assertTrue(allow_case_material_access(None, 1, None))  # no rbac wired


if __name__ == "__main__":
    unittest.main()
