#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents.orchestrator import (  # noqa: E402
    RetrievalCache,
    classify_intent,
    guess_template_name,
    heuristic_plan,
    parse_orch_payload,
    run_orchestrate,
)


class TestOrchestrator(unittest.TestCase):
    def test_parse_orch_json_after_delimiter(self):
        text = '思考\n==ORCH==\n{"type":"plan","steps":[{"agent":"text_analysis","allow_subcalls":["legal_retrieval"]}]}'
        payload = parse_orch_payload(text)
        self.assertEqual(payload["type"], "plan")
        self.assertEqual(payload["steps"][0]["agent"], "text_analysis")

    def test_classify_intent_routes(self):
        self.assertEqual(classify_intent("帮我写一份要素式民间借贷起诉状"), "doc_writing")
        self.assertEqual(classify_intent("检索劳动合同法第64条"), "law_search")
        self.assertEqual(classify_intent("查找类似的民间借贷类案"), "case_search")
        self.assertEqual(classify_intent("请作为法官帮我断案"), "legal_analysis")
        self.assertEqual(classify_intent("请帮我做合同审查"), "contract_review")
        self.assertEqual(classify_intent("你好"), "chitchat")
        self.assertEqual(classify_intent("今天天气怎么样"), "chitchat")

    def test_heuristic_analysis_allows_retrieval(self):
        plan = heuristic_plan("请结合法规分析这份案情：原告张三与被告李四因借款发生争议")
        self.assertEqual(plan["intent"], "legal_analysis")
        self.assertEqual(plan["steps"][0]["agent"], "text_analysis")
        self.assertIn("legal_retrieval", plan["steps"][0]["allow_subcalls"])
        self.assertEqual(plan.get("retrieval_scopes"), ["law", "case"])

    def test_heuristic_chitchat_skips_kb(self):
        plan = heuristic_plan("你好呀")
        self.assertEqual(plan["intent"], "chitchat")
        self.assertEqual(plan["steps"][0]["allow_subcalls"], [])
        self.assertEqual(plan.get("retrieval_scopes"), [])

    def test_heuristic_law_and_case_search(self):
        law = heuristic_plan("帮我检索民法典关于善意取得的规定")
        self.assertEqual(law["intent"], "law_search")
        self.assertEqual(law["steps"][0]["agent"], "legal_retrieval")
        self.assertEqual(law.get("retrieval_scopes"), ["law"])
        case = heuristic_plan("帮我查找劳动争议类案")
        self.assertEqual(case["intent"], "case_search")
        self.assertEqual(case.get("retrieval_scopes"), ["case"])

    def test_guess_template_name(self):
        self.assertEqual(guess_template_name("帮我生成民间借贷纠纷起诉状"), "民间借贷纠纷起诉状")
        self.assertEqual(guess_template_name("起草离婚协议"), "离婚协议书")
        plan = heuristic_plan("帮我生成民间借贷纠纷起诉状")
        self.assertEqual(plan["steps"][0]["agent"], "doc_writing")

    def test_heuristic_judge_and_contract_use_skills_not_legacy(self):
        judge = heuristic_plan("请作为法官帮我断案")
        self.assertNotEqual(judge.get("type"), "legacy")
        self.assertEqual(judge["steps"][0]["agent"], "text_analysis")
        review = heuristic_plan("请帮我做合同审查")
        self.assertEqual(review["steps"][0]["agent"], "text_analysis")

    def test_retrieval_cache_key(self):
        cache = RetrievalCache()
        cache.put("民间借贷", {"text": "法条"})
        self.assertEqual(cache.get("民间借贷")["text"], "法条")
        self.assertIsNone(cache.get("其他"))

    def test_run_analysis_subcalls_retrieval(self):
        calls = []

        def retrieve(query, scopes=None):
            calls.append((query, tuple(scopes or ())))
            return {"laws": "合同法第五十二条", "cases": "类案A"}

        result = run_orchestrate(
            user_text="请结合法规和类案分析民间借贷纠纷，原告张三被告李四借款未还",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            file_service=None,
            skills=[],
        )
        self.assertTrue(calls)
        self.assertEqual(calls[0][1], ("law", "case"))
        self.assertEqual(result["agent"], "text_analysis")
        self.assertNotIn("合同法", result["visible_text"])
        self.assertNotIn("【法规】", result["visible_text"])
        self.assertIn("legal_retrieval", result.get("subcalls_used", []))
        caps = result.get("capabilities") or {}
        mcp_ids = [item["id"] for item in caps.get("mcp") or []]
        self.assertIn("legal://law_regulation", mcp_ids)
        self.assertIn("legal://similar_cases", mcp_ids)

    def test_analysis_bubbles_nested_retrieval_citations(self):
        cite = {
            "id": "c-law-1",
            "doc_type": "law",
            "document_id": "d1",
            "file_id": "f-law",
            "title": "民法典",
            "article": "第六百六十七条",
            "snippet": "借款合同",
            "rrf_score": 0.01,
        }

        def retrieve(query, scopes=None):
            return {
                "laws": "民法典第六百六十七条",
                "cases": "类案A",
                "law_citations": [cite],
                "case_citations": [],
            }

        result = run_orchestrate(
            user_text="请结合法规和类案分析民间借贷纠纷，原告张三被告李四借款未还",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            file_service=None,
            skills=[],
        )
        self.assertEqual(result["agent"], "text_analysis")
        self.assertIn("legal_retrieval", result.get("subcalls_used", []))
        cites = result.get("citations") or []
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["file_id"], "f-law")
        self.assertEqual(cites[0]["title"], "民法典")

    def test_doc_writing_bubbles_nested_retrieval_citations(self):
        cite = {
            "id": "c-law-2",
            "doc_type": "law",
            "document_id": "d2",
            "file_id": "f-doc",
            "title": "民事诉讼法",
            "article": "",
            "snippet": "起诉状",
            "rrf_score": 0.02,
        }

        def retrieve(query, scopes=None):
            return {
                "laws": "民事诉讼法",
                "cases": "",
                "law_citations": [cite],
                "case_citations": [],
            }

        result = run_orchestrate(
            user_text="请生成民间借贷纠纷起诉状，原告张三，被告李四，借款10万元。",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            file_service=None,
            skills=[],
        )
        self.assertEqual(result["agent"], "doc_writing")
        self.assertIn("legal_retrieval", result.get("subcalls_used", []))
        cites = result.get("citations") or []
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["file_id"], "f-doc")

    def test_chitchat_does_not_call_retrieve(self):
        calls = []

        def retrieve(query, scopes=None):
            calls.append(query)
            return {"laws": "x", "cases": "y"}

        result = run_orchestrate(
            user_text="你好",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            file_service=None,
            skills=[],
        )
        self.assertFalse(calls)
        self.assertEqual(result.get("plan", {}).get("intent"), "chitchat")
        self.assertTrue((result.get("visible_text") or "").strip())

    def test_law_search_scopes_law_only(self):
        calls = []

        def retrieve(query, scopes=None):
            calls.append(tuple(scopes or ()))
            return {"laws": "劳动合同法第六十四条", "cases": ""}

        result = run_orchestrate(
            user_text="检索劳动合同法第64条",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            file_service=None,
            skills=[],
        )
        self.assertEqual(result["agent"], "legal_retrieval")
        self.assertEqual(calls, [("law",)])
        self.assertIn("劳动合同法", result.get("visible_text") or "")

    def test_analysis_uses_skill_internally_not_as_reply(self):
        captured = {}
        skill_body = "禁止把这段话展示给用户。工作步骤：1.识别案由"

        def fake_llm(system, user, hist=None):
            captured["system"] = system
            captured["user"] = user
            return "请先补充原告与被告的姓名。"

        result = run_orchestrate(
            user_text="请作为法官帮我断案，有一笔借款未还",
            messages=[],
            llm=None,
            retrieve_fn=lambda q: {"laws": "", "cases": ""},
            file_service=None,
            skills=[{
                "id": "judge-work",
                "name": "法官断案指南",
                "applies_to": ["text_analysis"],
                "body": skill_body,
            }],
            write_llm=fake_llm,
        )
        self.assertEqual(result["visible_text"], "请先补充原告与被告的姓名。")
        self.assertIn(skill_body, captured.get("system") or "")
        self.assertNotIn(skill_body, result["visible_text"])
        self.assertNotIn("工作步骤", result["visible_text"])

    def test_bare_judge_request_does_not_dump_retrieval_or_skill(self):
        skill_body = "工作步骤：1.识别案由\n2.当事人是否适格"

        result = run_orchestrate(
            user_text="请帮我断案",
            messages=[],
            llm=None,
            retrieve_fn=lambda q: {"laws": "民法典第六百六十七条", "cases": "指导案例1号全文" * 20},
            file_service=None,
            skills=[{
                "id": "judge-work",
                "name": "法官断案指南",
                "applies_to": ["text_analysis"],
                "body": skill_body,
            }],
        )
        visible = result.get("visible_text") or ""
        self.assertNotIn("工作步骤", visible)
        self.assertNotIn("民法典", visible)
        self.assertNotIn("指导案例", visible)
        self.assertNotIn("【法规】", visible)
        self.assertEqual(result.get("subcalls_used") or [], [])
        self.assertIn("当事人", visible)
        flow_ids = [step.get("id") for step in (result.get("flow") or [])]
        self.assertIn("orchestrator", flow_ids)
        self.assertIn("text_analysis", flow_ids)
        self.assertIn("judge-work", flow_ids)
        self.assertNotIn("legal://law_regulation", flow_ids)
        self.assertEqual(flow_ids[-1], "return")

    def test_analysis_rejects_llm_that_echoes_skill(self):
        skill_body = "工作步骤：1.识别案由。禁止把这段话展示给用户。"

        def echo_llm(system, user, hist=None):
            return skill_body + "\n【法规】民法典"

        result = run_orchestrate(
            user_text="请帮我断案，张三借给李四十万未还",
            messages=[],
            llm=None,
            retrieve_fn=lambda q: {"laws": "民法典", "cases": ""},
            file_service=None,
            skills=[{
                "id": "judge-work",
                "name": "法官断案指南",
                "applies_to": ["text_analysis"],
                "body": skill_body,
            }],
            write_llm=echo_llm,
        )
        self.assertNotIn("工作步骤", result["visible_text"])
        self.assertNotIn("【法规】", result["visible_text"])

    def test_langgraph_trace_lists_agents_skills_mcp(self):
        result = run_orchestrate(
            user_text="请结合法规和类案分析民间借贷纠纷",
            messages=[],
            llm=None,
            retrieve_fn=lambda q: {"laws": "合同法第五十二条", "cases": "类案A"},
            file_service=None,
            skills=[{
                "id": "case-facts",
                "name": "案情拆解",
                "applies_to": ["text_analysis"],
                "body": "列出当事人",
            }],
        )
        caps = result.get("capabilities") or {}
        agent_ids = [item["id"] for item in caps.get("agents") or []]
        self.assertIn("orchestrator", agent_ids + [t["id"] for t in (caps.get("trace") or []) if t.get("kind") == "agent"])
        self.assertIn("text_analysis", agent_ids or [t["id"] for t in (caps.get("trace") or []) if t.get("kind") == "agent"])
        self.assertTrue(
            any(t.get("kind") == "mcp" and "law_regulation" in (t.get("id") or "") for t in (caps.get("trace") or caps.get("mcp") or []))
        )
        self.assertTrue(
            any((item.get("id") == "case-facts") for item in (caps.get("skills") or []))
            or any(t.get("id") == "case-facts" for t in (caps.get("trace") or []))
        )
        if result.get("runtime") == "langgraph":
            kinds = [(t["kind"], t["id"]) for t in caps.get("trace") or []]
            self.assertIn(("agent", "orchestrator"), kinds)
            self.assertIn(("agent", "text_analysis"), kinds)
            self.assertIn(("agent", "legal_retrieval"), kinds)
        flow = result.get("flow") or (caps.get("flow") or [])
        ids = [step.get("id") for step in flow]
        self.assertTrue(flow)
        self.assertEqual(ids[0], "orchestrator")
        self.assertIn("text_analysis", ids)
        self.assertIn("case-facts", ids)
        self.assertIn("legal_retrieval", ids)
        self.assertIn("legal://law_regulation", ids)
        self.assertEqual(ids[-1], "return")
        self.assertLess(ids.index("text_analysis"), ids.index("case-facts"))
        self.assertLess(ids.index("case-facts"), ids.index("legal_retrieval"))
        self.assertLess(ids.index("legal_retrieval"), ids.index("legal://law_regulation"))

    def test_writer_complete_builds_artifact_when_file_service_present(self):
        class FakeFiles:
            def save_file(self, file_data, original_filename, session_id=None, description=None, metadata=None):
                self.data = file_data
                return {"file_id": "fid-1", "original_name": original_filename}

        files = FakeFiles()
        result = run_orchestrate(
            user_text="请生成民间借贷纠纷起诉状，原告张三，被告李四，借款10万元。导出文书。",
            messages=[],
            llm=None,
            retrieve_fn=lambda q: {"laws": "民法典", "cases": ""},
            file_service=files,
            skills=[],
            session_id="s1",
        )
        self.assertEqual(result["agent"], "doc_writing")
        self.assertIsNotNone(result.get("artifact"))
        self.assertTrue(result["artifact"]["filename"].endswith(".docx"))
        self.assertTrue(files.data.startswith(b"PK"))
        self.assertIn("当事人", result.get("draft") or "")
        self.assertNotIn("根据用户请求生成", result.get("draft") or "")

    def test_writer_records_skill_and_template_mcp(self):
        result = run_orchestrate(
            user_text="请生成民间借贷纠纷起诉状并导出文书",
            messages=[],
            llm=None,
            retrieve_fn=lambda q: {"laws": "民法典", "cases": ""},
            file_service=None,
            skills=[{
                "id": "legal-doc-guide",
                "name": "法律文书生成指南",
                "applies_to": ["doc_writing"],
                "body": "按模板填写",
            }],
            template_fn=lambda name: "模板正文",
        )
        caps = result.get("capabilities") or {}
        skill_ids = [item["id"] for item in caps.get("skills") or []]
        mcp_ids = [item["id"] for item in caps.get("mcp") or []]
        self.assertIn("legal-doc-guide", skill_ids)
        self.assertIn("legal://doc_template", mcp_ids)

    def test_llm_gate_law_search_uses_kb(self):
        os.environ["PLAN_EXECUTE"] = "0"
        try:
            calls = {"n": 0, "retrieve": []}

            def write_llm(system, user, hist=None):
                calls["n"] += 1
                if calls["n"] == 1:
                    return '{"domain":"legal","intent":"law_search"}'
                return "unused"

            def retrieve(q, scopes=None):
                calls["retrieve"].append(tuple(scopes or ()))
                return {
                    "laws": "劳动合同法第六十四条",
                    "cases": "",
                    "law_citations": [],
                    "case_citations": [],
                }

            result = run_orchestrate(
                user_text="检索劳动合同法第64条",
                messages=[],
                llm=None,
                retrieve_fn=retrieve,
                write_llm=write_llm,
                skills=[],
            )
            self.assertEqual(calls["retrieve"], [("law",)])
            self.assertEqual(result.get("plan", {}).get("intent"), "law_search")
        finally:
            os.environ.pop("PLAN_EXECUTE", None)

    def test_llm_gate_non_legal_skips_retrieve(self):
        retrieve_calls = []

        def write_llm(system, user, hist=None):
            if "分类" in system or "JSON" in system or "intent" in system.lower():
                return '{"domain":"non_legal"}'
            return "今天适合出门。"

        def retrieve(q, scopes=None):
            retrieve_calls.append(q)
            return {"laws": "x", "cases": "y"}

        result = run_orchestrate(
            user_text="今天天气怎么样",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            write_llm=write_llm,
            skills=[],
        )
        self.assertFalse(retrieve_calls)
        self.assertIn("更擅长", result["visible_text"])
        self.assertIn("今天适合出门", result["visible_text"])
        self.assertEqual(result.get("plan", {}).get("intent"), "non_legal")
        self.assertEqual(result.get("citations") or [], [])
        self.assertEqual(result.get("orchestration_mode"), "non_legal")

    def test_legal_gate_uses_plan_execute_when_enabled(self):
        import os
        os.environ.pop("PLAN_EXECUTE", None)  # default on

        from agents.intent_gate import CLASSIFY_SYSTEM

        def write_llm(system, user, hist=None):
            if system == CLASSIFY_SYSTEM:
                return '{"domain":"legal","intent":"legal_analysis"}'
            if "步骤列表" in (system or "") or "规划" in (system or ""):
                return '{"plan":["给出简要法律意见"]}'
            if "选一个工具" in (system or ""):
                return '{"tool":"reason","args":{"prompt":"x"}}'
            return '{"action":"response","response":"PnE答复"}'

        result = run_orchestrate(
            user_text="请分析民间借贷纠纷焦点",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=lambda q, scopes=None: {"text": "", "citations": []},
        )
        self.assertEqual(result.get("orchestration_mode"), "plan_execute")
        self.assertIn("PnE", result.get("visible_text") or "")

    def test_plan_execute_disabled_uses_legacy_graph(self):
        import os
        os.environ["PLAN_EXECUTE"] = "0"
        try:
            from agents.intent_gate import CLASSIFY_SYSTEM

            def write_llm(system, user, hist=None):
                if system == CLASSIFY_SYSTEM:
                    return '{"domain":"legal","intent":"legal_analysis"}'
                # analysis path may call write_llm for final text
                return "旧路径分析答复"

            result = run_orchestrate(
                user_text="请分析民间借贷纠纷焦点",
                messages=[],
                write_llm=write_llm,
                retrieve_fn=lambda q, scopes=None: {"text": "法", "citations": []},
            )
            self.assertNotEqual(result.get("orchestration_mode"), "plan_execute")
            # old path uses specialist plan with steps/agents
            plan = result.get("plan") or {}
            self.assertTrue(plan.get("steps") or result.get("agent"))
        finally:
            os.environ.pop("PLAN_EXECUTE", None)

    def test_llm_gate_bad_json_falls_back_to_keyword(self):
        retrieve_calls = []

        def write_llm(system, user, hist=None):
            if "JSON" in system or "分类" in system:
                return "不是json"
            return "ok"

        def retrieve(q, scopes=None):
            retrieve_calls.append(q)
            return {"laws": "x", "cases": "y"}

        result = run_orchestrate(
            user_text="你好",
            messages=[],
            llm=None,
            retrieve_fn=retrieve,
            write_llm=write_llm,
            skills=[],
        )
        self.assertFalse(retrieve_calls)
        self.assertEqual(result.get("plan", {}).get("intent"), "chitchat")

    def test_case_materials_prefix_reaches_analysis_llm(self):
        from unittest.mock import MagicMock

        from case_materials import build_case_material_context

        os.environ["PLAN_EXECUTE"] = "0"
        try:
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
                    return {
                        "file_id": "c1",
                        "original_name": "委托.pdf",
                        "file_type": "pdf",
                        "text_content": "合同正文内容",
                        "metadata": {},
                    }
                return {
                    "file_id": "e1",
                    "original_name": "转账.png",
                    "file_type": "png",
                    "text_content": "长正文不应注入",
                    "metadata": {"evidence_brief": "银行转账截图"},
                }

            fs.get_file.side_effect = get_file
            fs.get_file_text.side_effect = lambda fid: get_file(fid).get("text_content")
            case_ctx = build_case_material_context(1, store, fs)
            self.assertIn("【当前案件】", case_ctx)
            enriched = case_ctx + "\n\n请结合案情帮我分析"

            captured = {}

            def write_llm(system, user, hist=None):
                if "意图分类器" in (system or ""):
                    return '{"domain":"legal","intent":"legal_analysis"}'
                captured["user"] = user
                return "分析结论：请补充还款凭证。"

            result = run_orchestrate(
                user_text=enriched,
                messages=[],
                llm=None,
                retrieve_fn=lambda q, scopes=None: {"laws": "", "cases": ""},
                file_service=fs,
                skills=[],
                write_llm=write_llm,
                case_id=1,
                case_store=store,
            )
            self.assertIn("【当前案件】", captured.get("user") or "")
            self.assertIn("合同正文内容", captured.get("user") or "")
            self.assertNotIn("长正文不应注入", captured.get("user") or "")
            self.assertIn("分析结论", result.get("visible_text") or "")
        finally:
            os.environ.pop("PLAN_EXECUTE", None)

    def test_evidence_tool_round_uses_second_llm_reply(self):
        from unittest.mock import MagicMock

        os.environ["PLAN_EXECUTE"] = "0"
        try:
            store = MagicMock()
            store.get_case.return_value = {
                "id": 1,
                "meta": {"evidence_file_ids": ["e1"]},
            }
            fs = MagicMock()
            fs.get_file.return_value = {
                "file_id": "e1",
                "original_name": "转账.png",
                "text_content": "转账金额十万元已到账",
                "metadata": {},
            }
            fs.get_file_text.return_value = "转账金额十万元已到账"

            analysis_calls = []

            def write_llm(system, user, hist=None):
                if "意图分类器" in (system or ""):
                    return '{"domain":"legal","intent":"legal_analysis"}'
                analysis_calls.append(user)
                if len(analysis_calls) == 1:
                    return '{"tool":"get_case_evidence_file","file_id":"e1"}'
                return "终答：证据显示已转账十万元。"

            result = run_orchestrate(
                user_text="请结合证据分析民间借贷纠纷，原告张三被告李四借款未还",
                messages=[],
                llm=None,
                retrieve_fn=lambda q, scopes=None: {"laws": "", "cases": ""},
                file_service=fs,
                skills=[],
                write_llm=write_llm,
                case_id=1,
                case_store=store,
            )
            self.assertEqual(len(analysis_calls), 2)
            self.assertIn("【证据全文】", analysis_calls[1])
            self.assertIn("转账金额十万元已到账", analysis_calls[1])
            self.assertEqual(result.get("visible_text"), "终答：证据显示已转账十万元。")
            self.assertNotIn("get_case_evidence_file", result.get("visible_text") or "")
        finally:
            os.environ.pop("PLAN_EXECUTE", None)

    def test_handle_orchestrate_injects_case_keeps_original_history(self):
        from unittest.mock import MagicMock, patch

        from http_api_extra import handle_orchestrate

        store = MagicMock()
        store.get_case.return_value = {
            "id": 7,
            "case_no": "B7",
            "title": "合同纠纷",
            "meta": {
                "case_type": "civil",
                "contract_file_ids": [],
                "evidence_file_ids": [],
            },
        }
        fs = MagicMock()
        session = MagicMock()
        session.get_session.return_value = {"id": "s1"}
        mcp = MagicMock()
        mcp.rbac_store = store
        mcp.rbac_api = None
        mcp.file_service = fs
        mcp.session_service = session
        mcp._handle_resource_read.return_value = {"result": {"contents": [{"text": ""}]}}

        captured = {}

        def fake_run(**kwargs):
            captured["user_text"] = kwargs.get("user_text")
            captured["case_id"] = kwargs.get("case_id")
            captured["case_store"] = kwargs.get("case_store")
            return {"visible_text": "ok", "agent": "text_analysis"}

        with patch("http_api_extra.run_orchestrate", side_effect=fake_run), patch(
            "http_api_extra.skill_service"
        ) as skill_svc, patch("http_api_extra.make_retrieve_fn", return_value=lambda q: {}):
            skill_svc.return_value.match.return_value = []
            result = handle_orchestrate(
                mcp,
                {"user_text": "请帮我分析本案", "case_id": 7, "session_id": "s1"},
            )

        self.assertIn("【当前案件】", captured.get("user_text") or "")
        self.assertIn("请帮我分析本案", captured.get("user_text") or "")
        self.assertEqual(captured.get("case_id"), 7)
        self.assertIs(captured.get("case_store"), store)
        session.add_message.assert_any_call("s1", "user", "请帮我分析本案")
        user_calls = [
            c for c in session.add_message.call_args_list if c.args[1] == "user"
        ]
        self.assertEqual(len(user_calls), 1)
        self.assertNotIn("【当前案件】", user_calls[0].args[2])
        self.assertTrue(result.get("saved_to_session"))

    def test_handle_orchestrate_star_skips_material_inject(self):
        from unittest.mock import MagicMock, patch

        from http_api_extra import handle_orchestrate

        store = MagicMock()
        store.list_cases_for_user.return_value = [{"id": 7}, {"id": 8}]
        rbac = MagicMock()
        rbac.rbac.require.return_value = True
        rbac.store = store
        mcp = MagicMock()
        mcp.rbac_api = rbac
        mcp.rbac_store = store
        mcp.file_service = MagicMock()
        mcp.session_service = None
        mcp._handle_resource_read.return_value = {"result": {"contents": [{"text": ""}]}}

        captured = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"visible_text": "ok", "agent": "text_analysis"}

        with patch("http_api_extra.run_orchestrate", side_effect=fake_run), patch(
            "http_api_extra.skill_service"
        ) as skill_svc, patch("http_api_extra.make_retrieve_fn", return_value=lambda q: {}), patch(
            "case_materials.build_case_material_context"
        ) as build_ctx:
            skill_svc.return_value.match.return_value = []
            handle_orchestrate(
                mcp,
                {
                    "user_text": "请分析",
                    "case_id": "*",
                    "_auth_user_id": 42,
                },
            )

        build_ctx.assert_not_called()
        self.assertNotIn("【当前案件】", captured.get("user_text") or "")
        self.assertEqual(captured.get("case_scope"), "all_permitted")
        self.assertEqual(captured.get("permitted_case_ids"), [7, 8])
        self.assertIsNone(captured.get("case_id"))

    def test_handle_orchestrate_passes_resume_state_and_persists_awaiting(self):
        from unittest.mock import MagicMock, patch

        from http_api_extra import handle_orchestrate

        session = MagicMock()
        session.get_session.return_value = {"id": "s-resume"}
        mcp = MagicMock()
        mcp.rbac_store = None
        mcp.rbac_api = None
        mcp.file_service = None
        mcp.session_service = session
        mcp._handle_resource_read.return_value = {"result": {"contents": [{"text": ""}]}}

        resume_in = {
            "objective": "查明合同效力",
            "plan": ["检索法条", "ask_user"],
            "past_steps": [{"step": "检索法条", "result": "ok"}],
            "tool_calls_used": 1,
            "replan_count": 0,
        }
        resume_out = {
            **resume_in,
            "past_steps": resume_in["past_steps"] + [{"step": "ask_user", "result": "pending"}],
        }
        captured = {}

        def fake_run(**kwargs):
            captured["resume_state"] = kwargs.get("resume_state")
            return {
                "visible_text": "",
                "pending_question": "请补充合同签订日期？",
                "status": "awaiting_user",
                "plan": ["检索法条", "ask_user"],
                "past_steps": resume_out["past_steps"],
                "resume_state": resume_out,
                "orchestration_mode": "plan_execute",
            }

        with patch("http_api_extra.run_orchestrate", side_effect=fake_run), patch(
            "http_api_extra.skill_service"
        ) as skill_svc, patch("http_api_extra.make_retrieve_fn", return_value=lambda q: {}):
            skill_svc.return_value.match.return_value = []
            result = handle_orchestrate(
                mcp,
                {
                    "user_text": "大概是去年签的",
                    "session_id": "s-resume",
                    "resume_state": resume_in,
                },
            )

        self.assertEqual(captured.get("resume_state"), resume_in)
        self.assertEqual(result.get("status"), "awaiting_user")
        self.assertTrue(result.get("saved_to_session"))
        assistant_calls = [
            c for c in session.add_message.call_args_list if c.args[1] == "assistant"
        ]
        self.assertEqual(len(assistant_calls), 1)
        self.assertEqual(assistant_calls[0].args[2], "请补充合同签订日期？")
        extra = assistant_calls[0].kwargs.get("extra") or {}
        self.assertEqual(extra.get("resume_state"), resume_out)
        self.assertEqual(extra.get("plan"), ["检索法条", "ask_user"])
        self.assertEqual(extra.get("past_steps"), resume_out["past_steps"])
        self.assertEqual(extra.get("status"), "awaiting_user")


if __name__ == "__main__":
    unittest.main()
