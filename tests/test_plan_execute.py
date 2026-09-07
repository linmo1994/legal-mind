#!/usr/bin/env python3
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from agents.plan_execute import (  # noqa: E402
    EXECUTOR_SYSTEM,
    MAX_REPLANS,
    MAX_TOOL_CALLS,
    PLANNER_SYSTEM,
    REPLAN_SYSTEM,
    _CASE_RETRIEVE_STEP,
    _LAW_RETRIEVE_STEP,
    _ensure_retrieve_steps,
    run_plan_execute,
)
from agents.workflow import (  # noqa: E402
    WorkflowTracer,
    bind_workflow,
    emit_step,
    reset_workflow,
)


class TestPlanExecute(unittest.TestCase):
    def test_happy_path_retrieve_then_response(self):
        calls = {"n": 0}

        def write_llm(system, user, hist=None):
            calls["n"] += 1
            s = system or ""
            if "规划" in s or "planner" in s.lower() or "步骤列表" in s:
                return '{"plan":["检索民间借贷利率规定","结合材料给出结论"]}'
            if "选择工具" in s or "executor" in s.lower() or "选一个工具" in s:
                return '{"tool":"retrieve_law","args":{"query":"民间借贷利率"}}'
            return '{"action":"response","response":"利率应受保护限度约束。"}'

        def retrieve(query, scopes=None):
            return {"text": "法条…", "citations": [{"title": "民法典"}]}

        out = run_plan_execute(
            objective="借款利率是否合法",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=retrieve,
        )
        self.assertEqual(out["status"], "complete")
        self.assertIn("利率", out["visible_text"])
        self.assertEqual(out["orchestration_mode"], "plan_execute")
        self.assertGreaterEqual(len(out["past_steps"]), 1)
        self.assertTrue(out.get("citations"))

    def test_ask_user_then_resume(self):
        phase = {"p": "plan"}

        def write_llm(system, user, hist=None):
            s = system or ""
            if "步骤列表" in s or "规划" in s:
                return '{"plan":["确认借款金额"]}'
            if "选一个工具" in s:
                return '{"tool":"reason","args":{"prompt":"检查是否有金额"}}'
            if phase["p"] == "plan":
                phase["p"] = "resume"
                return '{"action":"ask_user","question":"借款本金是多少？"}'
            return '{"action":"response","response":"本金按您补充的金额计算。"}'

        first = run_plan_execute(
            objective="分析借贷",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=lambda q, scopes=None: {},
        )
        self.assertEqual(first["status"], "awaiting_user")
        self.assertIn("本金", first["pending_question"])
        resume = first["resume_state"]
        second = run_plan_execute(
            objective="本金10万元",
            messages=[{"role": "user", "content": "本金10万元"}],
            write_llm=write_llm,
            retrieve_fn=lambda q, scopes=None: {},
            resume_state=resume,
        )
        self.assertEqual(second["status"], "complete")
        self.assertIn("本金", second["visible_text"])

    def test_budget_stops(self):
        def write_llm(system, user, hist=None):
            s = system or ""
            if "步骤列表" in s or "规划" in s:
                return '{"plan":["a","b","c"]}'
            if "选一个工具" in s:
                return '{"tool":"reason","args":{"prompt":"x"}}'
            return '{"action":"continue","plan":["keep-going"]}'

        out = run_plan_execute(
            objective="x",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=None,
            max_replans=2,
            max_tool_calls=3,
        )
        self.assertIn(out["status"], ("complete", "error"))
        self.assertLessEqual(out.get("replan_count", 0), 2)
        self.assertLessEqual(out.get("tool_calls_used", 0), 3)

    def test_resume_at_budget_forces_wrap(self):
        replan_calls = {"n": 0}

        def write_llm(system, user, hist=None):
            s = system or ""
            # Would keep asking if resume replan were allowed
            if "规划" not in s and "步骤列表" not in s and "选一个工具" not in s:
                replan_calls["n"] += 1
                return '{"action":"ask_user","question":"还需要更多信息？"}'
            return '{"plan":["x"]}'

        resume = {
            "objective": "分析借贷",
            "plan": [],
            "past_steps": [
                {"step": "确认金额", "observation": "缺本金", "tool": "reason"},
            ],
            "tool_calls_used": 1,
            "replan_count": 2,
        }
        out = run_plan_execute(
            objective="本金10万",
            messages=[{"role": "user", "content": "本金10万"}],
            write_llm=write_llm,
            retrieve_fn=None,
            resume_state=resume,
            max_replans=2,
        )
        self.assertEqual(out["status"], "complete")
        self.assertEqual(out["replan_count"], 2)
        # Forced wrap may call write_llm once; must not run a counting replan past the cap
        self.assertLessEqual(out["replan_count"], 2)

    def test_emit_detail_optional_on_tracer(self):
        tracer = WorkflowTracer()
        token = bind_workflow(tracer)
        try:
            emit_step("agent", "orchestrator", "编排", status="done")
            emit_step(
                "plan",
                "plan",
                "执行计划",
                detail={"steps": ["检索法规", "给出结论"]},
            )
        finally:
            reset_workflow(token)
        self.assertEqual(len(tracer.events), 2)
        self.assertNotIn("detail", tracer.events[0])
        self.assertEqual(
            tracer.events[1]["detail"],
            {"steps": ["检索法规", "给出结论"]},
        )

    def test_happy_path_emits_plan_event(self):
        def write_llm(system, user, hist=None):
            s = system or ""
            if "规划" in s or "planner" in s.lower() or "步骤列表" in s:
                return '{"plan":["检索民间借贷利率规定","结合材料给出结论"]}'
            if "选择工具" in s or "executor" in s.lower() or "选一个工具" in s:
                return '{"tool":"retrieve_law","args":{"query":"民间借贷利率"}}'
            return '{"action":"response","response":"利率应受保护限度约束。"}'

        tracer = WorkflowTracer()
        token = bind_workflow(tracer)
        try:
            out = run_plan_execute(
                objective="借款利率是否合法",
                messages=[],
                write_llm=write_llm,
                retrieve_fn=lambda q, scopes=None: {
                    "text": "法条…",
                    "citations": [{"title": "民法典"}],
                },
            )
        finally:
            reset_workflow(token)

        self.assertEqual(out["status"], "complete")
        plan_events = [e for e in tracer.events if e.get("kind") == "plan"]
        self.assertTrue(plan_events, "expected a plan event in tracer.events")
        first = plan_events[0]
        self.assertEqual(first.get("id"), "plan")
        self.assertEqual(first.get("name"), "执行计划")
        self.assertIn("steps", first.get("detail") or {})
        self.assertGreaterEqual(len(first["detail"]["steps"]), 1)
        step_events = [e for e in tracer.events if e.get("kind") == "plan_step"]
        self.assertTrue(step_events)
        statuses = {e.get("status") for e in step_events}
        self.assertIn("running", statuses)
        self.assertIn("done", statuses)

    def test_retrieve_law_miss_emits_external_search(self):
        def write_llm(system, user, hist=None):
            s = system or ""
            if "规划" in s or "planner" in s.lower() or "步骤列表" in s:
                return '{"plan":["检索某某不存在法","给出结论"]}'
            if "选择工具" in s or "executor" in s.lower() or "选一个工具" in s:
                return '{"tool":"retrieve_law","args":{"query":"某某不存在法第一条"}}'
            return '{"action":"response","response":"本地未命中，请查阅官网。"}'

        tracer = WorkflowTracer()
        token = bind_workflow(tracer)
        try:
            out = run_plan_execute(
                objective="某某不存在法第一条怎么适用",
                messages=[],
                write_llm=write_llm,
                retrieve_fn=lambda q, scopes=None: {
                    "laws": "",
                    "law_citations": [],
                },
            )
        finally:
            reset_workflow(token)

        self.assertEqual(out["status"], "complete")
        self.assertTrue(out.get("external_search", {}).get("needed"))
        self.assertEqual(out["external_search"].get("provider"), "npc_flk")
        external_events = [e for e in tracer.events if e.get("kind") == "external"]
        self.assertTrue(external_events, "expected an external event in tracer.events")
        self.assertEqual(external_events[0].get("id"), "npc_flk")


    def test_draft_doc_artifact_bubbles_to_result(self):
        class FakeFS:
            def save_file(self, data, filename, session_id=None, description=None):
                return {"file_id": "pe-doc-1", "original_name": filename}

        def write_llm(system, user, hist=None):
            s = system or ""
            if "步骤列表" in s or "规划" in s:
                return '{"plan":["起草起诉状"]}'
            if "选一个工具" in s:
                return '{"tool":"draft_doc","args":{"prompt":"生成起诉状"}}'
            # tool-internal write for draft_doc body
            if "法律文书助手" in s or "内部技能" in s or "文书" in s:
                return "民事起诉状\n此致\n人民法院"
            return '{"action":"response","response":"已完成起诉状起草。"}'

        out = run_plan_execute(
            objective="生成一份起诉状",
            messages=[],
            write_llm=write_llm,
            file_service=FakeFS(),
            session_id="s1",
        )
        self.assertEqual(out["status"], "complete")
        art = out.get("artifact") or {}
        self.assertEqual(art.get("file_id"), "pe-doc-1")
        self.assertTrue(str(art.get("filename") or "").endswith(".docx"))

    def test_auto_draft_when_ask_user_despite_export_intent(self):
        """Model may ask for case; with 导出文书 we still force draft_doc + artifact."""
        class FakeFS:
            def save_file(self, data, filename, session_id=None, description=None):
                return {"file_id": "pe-auto-1", "original_name": filename}

        calls = {"exec": 0}

        def write_llm(system, user, hist=None):
            s = system or ""
            if "步骤列表" in s or "规划" in s:
                return '{"plan":["读取证据","起草起诉状"]}'
            if "选一个工具" in s:
                calls["exec"] += 1
                # First turn: avoid draft_doc (the bug we fix)
                return '{"tool":"read_evidence","args":{}}'
            if "收口" in s or "三种动作" in s or "continue" in s:
                return '{"action":"ask_user","question":"请选择案件或粘贴当事人信息"}'
            if "法律文书助手" in s or "内部技能" in s or "文书" in s:
                return "民事起诉状\n原告：张三\n被告：李四\n此致\n人民法院"
            return '{"action":"response","response":"请先选案件"}'

        out = run_plan_execute(
            objective="请生成民间借贷纠纷起诉状，原告张三被告李四。导出文书。",
            messages=[],
            write_llm=write_llm,
            file_service=FakeFS(),
            session_id="s-auto",
            case_id=None,
        )
        self.assertEqual(out["status"], "complete")
        art = out.get("artifact") or {}
        self.assertEqual(art.get("file_id"), "pe-auto-1")
        self.assertTrue(str(art.get("filename") or "").endswith(".docx"))
        tools = [p.get("tool") for p in (out.get("past_steps") or [])]
        self.assertIn("draft_doc", tools)

    def test_prompts_mention_retrieve_tools(self):
        self.assertIn("retrieve_law", PLANNER_SYSTEM)
        self.assertIn("retrieve_case", PLANNER_SYSTEM)
        self.assertIn("retrieve_law", EXECUTOR_SYSTEM)
        self.assertIn("retrieve_case", REPLAN_SYSTEM)

    def test_ensure_retrieve_steps_injects_law_when_article_query(self):
        plan = ["直接给出结论"]
        out = _ensure_retrieve_steps(
            "请检索劳动合同法第64条并回答",
            plan,
            [],
            max_steps=8,
        )
        self.assertTrue(any("法规" in s or "法条" in s for s in out[:2]))
        self.assertLessEqual(len(out), 8)

    def test_ensure_retrieve_steps_injects_when_plan_only_mentions_legal(self):
        out = _ensure_retrieve_steps(
            "劳动合同法第64条非全日制用工要点",
            ["分析法律责任"],
            [],
            max_steps=8,
        )
        self.assertIn(_LAW_RETRIEVE_STEP, out)
        self.assertEqual(out[0], _LAW_RETRIEVE_STEP)

    def test_ensure_retrieve_steps_skips_if_retrieve_law_done(self):
        plan = ["给出结论"]
        past = [{"tool": "retrieve_law", "observation": "..."}]
        out = _ensure_retrieve_steps(
            "劳动合同法第六十四条",
            plan,
            past,
            max_steps=8,
        )
        self.assertEqual(out, ["给出结论"])

    def test_ensure_retrieve_steps_injects_case_when_requested(self):
        plan = ["分析争议焦点"]
        out = _ensure_retrieve_steps(
            "帮我检索类似案例作为参考",
            plan,
            [],
            max_steps=8,
        )
        self.assertTrue(any("类案" in s or "案例" in s for s in out[:2]))

    def test_ensure_retrieve_steps_dual_for_win_analysis(self):
        """Entity-law advice (e.g. 胜诉) defaults to both law and case retrieve."""
        out = _ensure_retrieve_steps(
            "张三借了我1万元，请帮我分析是否能胜诉",
            ["直接给出结论"],
            [],
            max_steps=8,
        )
        self.assertEqual(out[0], _LAW_RETRIEVE_STEP)
        self.assertEqual(out[1], _CASE_RETRIEVE_STEP)
        self.assertIn("直接给出结论", out)

    def test_ensure_retrieve_steps_case_only_strips_law(self):
        """Explicit case lookup must not inject or keep law retrieve steps."""
        out = _ensure_retrieve_steps(
            "查找餐饮服务合同违约10倍赔偿的案例",
            ["检索相关法规并整理可引用条文", "直接回答"],
            [],
            max_steps=8,
        )
        self.assertEqual(out[0], _CASE_RETRIEVE_STEP)
        self.assertNotIn(_LAW_RETRIEVE_STEP, out)
        self.assertTrue(all("法规" not in s and "法条" not in s for s in out))

    def test_ensure_retrieve_steps_law_only_skips_case(self):
        out = _ensure_retrieve_steps(
            "请检索劳动合同法第64条",
            ["检索相关类案并整理可引用案例", "回答"],
            [],
            max_steps=8,
        )
        self.assertIn(_LAW_RETRIEVE_STEP, out)
        self.assertNotIn(_CASE_RETRIEVE_STEP, out)

    def test_injected_law_step_runs_retrieve(self):
        def write_llm(system, user, hist=None):
            s = system or ""
            if "步骤列表" in s or "规划" in s:
                return '{"plan":["直接回答非全日制要点"]}'
            if "选一个工具" in s:
                # first step should be injected retrieve
                return '{"tool":"retrieve_law","args":{"query":"劳动合同法第六十四条"}}'
            return '{"action":"response","response":"依据《中华人民共和国劳动合同法》第六十四条……"}'

        def retrieve(query, scopes=None):
            return {
                "laws": "…",
                "law_citations": [
                    {
                        "title": "中华人民共和国劳动合同法",
                        "article": "第六十四条",
                        "file_id": "f1",
                    }
                ],
                "case_citations": [],
            }

        out = run_plan_execute(
            objective="请检索劳动合同法第64条并引用法条回答非全日制用工要点",
            messages=[],
            write_llm=write_llm,
            retrieve_fn=retrieve,
        )
        self.assertEqual(out["status"], "complete")
        tools = [p.get("tool") for p in out.get("past_steps") or []]
        self.assertIn("retrieve_law", tools)
        self.assertTrue(out.get("citations"))


if __name__ == "__main__":
    unittest.main()
