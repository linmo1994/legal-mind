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
        self.assertEqual(m["validity"], "有效")
        m2 = normalize_case_meta({"case_kind": "guiding", "judges": "甲", "validity": "失效"})
        self.assertEqual(m2["case_kind"], "guiding")
        self.assertEqual(m2["validity"], "失效")

    def test_extract_success(self):
        def fake(system, user):
            return '{"law_name":"X法","effect_level":"法律","issuing_authority":"全国人大","document_number":"","effective_date":"2008-01-01"}'

        meta, status = extract_metadata("law", "正文", complete_fn=fake)
        self.assertEqual(status, "ready")
        self.assertEqual(meta["law_name"], "X法")
        self.assertEqual(meta["validity"], "有效")

    def test_extract_failure_returns_empty_meta(self):
        def fake(system, user):
            return "不是JSON"

        meta, status = extract_metadata("case", "正文", complete_fn=fake)
        self.assertEqual(status, "meta_failed")
        self.assertEqual(meta["case_kind"], "ordinary")
        self.assertEqual(meta["case_no"], "")
        self.assertEqual(meta["validity"], "有效")

    def test_extract_template_success(self):
        def fake(system, user):
            self.assertIn("要素式", system)
            self.assertIn("民间借贷纠纷起诉状", user)
            return (
                '{"template_name":"起诉状","document_type":"起诉状","case_category":"民事"}'
            )

        meta, status = extract_metadata(
            "template",
            "正文",
            complete_fn=fake,
            source_filename="民间借贷纠纷起诉状.docx",
        )
        self.assertEqual(status, "ready")
        self.assertEqual(meta["template_name"], "民间借贷纠纷起诉状")
        self.assertEqual(meta["document_type"], "起诉状")
        self.assertEqual(meta["case_category"], "民事")
        self.assertEqual(meta["validity"], "有效")

    def test_refine_template_name_from_filename(self):
        from kb_meta_extract import (
            is_bare_template_name,
            refine_template_meta,
            template_name_from_filename,
        )

        self.assertEqual(
            template_name_from_filename("path/民间借贷纠纷起诉状.docx"),
            "民间借贷纠纷起诉状",
        )
        self.assertTrue(is_bare_template_name("起诉状"))
        self.assertTrue(is_bare_template_name("民事起诉状"))
        self.assertFalse(is_bare_template_name("民间借贷纠纷起诉状"))
        m = refine_template_meta(
            {"template_name": "起诉状", "document_type": "起诉状", "case_category": "民事"},
            "民间借贷纠纷起诉状.docx",
        )
        self.assertEqual(m["template_name"], "民间借贷纠纷起诉状")
        m2 = refine_template_meta(
            {
                "template_name": "离婚纠纷答辩状",
                "document_type": "答辩状",
                "case_category": "民事",
            },
            "其它.docx",
        )
        self.assertEqual(m2["template_name"], "离婚纠纷答辩状")

    def test_normalize_template_enums(self):
        from kb_meta_extract import normalize_template_meta
        m = normalize_template_meta({
            "template_name": "x",
            "document_type": "判决书",
            "case_category": "执行",
        })
        self.assertEqual(m["document_type"], "")
        self.assertEqual(m["case_category"], "")
        self.assertEqual(m["validity"], "有效")
        m2 = normalize_template_meta({
            "template_name": "y",
            "document_type": "答辩状",
            "case_category": "刑事",
            "validity": "invalid",
        })
        self.assertEqual(m2["document_type"], "答辩状")
        self.assertEqual(m2["case_category"], "刑事")
        self.assertEqual(m2["validity"], "失效")

    def test_normalize_validity_aliases(self):
        from kb_meta_extract import normalize_law_meta
        self.assertEqual(normalize_law_meta({"validity": "expired"})["validity"], "失效")
        self.assertEqual(normalize_law_meta({"validity": "有效"})["validity"], "有效")
        self.assertEqual(normalize_law_meta({"validity": "其它"})["validity"], "有效")

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
