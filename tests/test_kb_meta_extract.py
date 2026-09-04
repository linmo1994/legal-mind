import unittest

from kb_meta_extract import extract_metadata, parse_json_object, normalize_case_meta


class TestKbMetaExtract(unittest.TestCase):
    def test_parse_fenced_json(self):
        raw = '```json\n{"law_name":"民法典","effect_level":"法律"}\n```'
        self.assertEqual(parse_json_object(raw)["law_name"], "民法典")

    def test_normalize_case_kind_and_judges(self):
        m = normalize_case_meta({
            "case_kind": "指导",
            "judges": ["甲", "乙"],
            "case_no": "1号",
        })
        self.assertEqual(m["case_kind"], "ordinary")  # 非法值回落
        self.assertEqual(m["judges"], "甲; 乙")
        m2 = normalize_case_meta({"case_kind": "guiding", "judges": "甲"})
        self.assertEqual(m2["case_kind"], "guiding")

    def test_extract_success(self):
        def fake(system, user):
            return '{"law_name":"X法","effect_level":"法律","issuing_authority":"全国人大","document_number":"","effective_date":"2008-01-01"}'

        meta, status = extract_metadata("law", "正文", complete_fn=fake)
        self.assertEqual(status, "ready")
        self.assertEqual(meta["law_name"], "X法")

    def test_extract_failure_returns_empty_meta(self):
        def fake(system, user):
            return "不是JSON"

        meta, status = extract_metadata("case", "正文", complete_fn=fake)
        self.assertEqual(status, "meta_failed")
        self.assertEqual(meta["case_kind"], "ordinary")
        self.assertEqual(meta["case_no"], "")

    def test_extract_transport_error_returns_meta_failed(self):
        def fake(system, user):
            raise OSError("timeout")

        meta, status = extract_metadata("law", "正文", complete_fn=fake)
        self.assertEqual(status, "meta_failed")
        self.assertEqual(meta["law_name"], "")
        self.assertEqual(meta["effect_level"], "")

    def test_invalid_doc_type_raises_before_try(self):
        with self.assertRaises(ValueError):
            extract_metadata("other", "正文", complete_fn=lambda s, u: "{}")


if __name__ == "__main__":
    unittest.main()
