import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.ai.agent_client import AIOpsAgent


class AgentDiagnosisTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_executes_selected_sql_tool_then_uses_result_in_followup(self):
        from backend.ai.agent_client import AIOpsAgent

        config = SimpleNamespace(
            DEEPSEEK_API_KEY="fixture-key",
            DEEPSEEK_API_BASE="https://example.invalid/v1",
            DEEPSEEK_TIMEOUT_SECONDS=1,
            DEEPSEEK_MODEL="fixture-model",
            DB_HOST="cn", DB_PORT=11003, DB_NAME="postgres", DB_USER="admin",
            EMBEDDING_MODEL="bge-m3", EMBEDDING_API_BASE="https://embed.invalid/v1",
            AIOPS_AUTO_AUDIT_ENABLED=True,
            AIOPS_AUTO_AUDIT_INTERVAL_SECONDS=900, AIOPS_AUTO_REPAIR_ENABLED=False,
            AIOPS_CANCEL_QUERY_ENABLED=False, AIOPS_REPAIR_DB_USER="",
            AIOPS_AUTO_AUDIT_TARGETS=(None,), AIOPS_AUTO_REPAIR_TARGETS=(),
            AIOPS_REPAIR_FUNCTION_ENABLED=False, AIOPS_REPAIR_FUNCTION_SCHEMA="aiops_admin",
            AIOPS_REPAIR_FUNCTION_NAME="analyze_table",
        )
        agent = AIOpsAgent(config)
        self.addCleanup(agent.client.close)
        tool_call = SimpleNamespace(
            id="sql-1",
            function=SimpleNamespace(name="execute_sql", arguments='{"sql":"SELECT 1 AS value"}'),
        )
        messages = [
            SimpleNamespace(content=None, tool_calls=[tool_call]),
            SimpleNamespace(content="查询返回 1。", tool_calls=[]),
        ]
        with patch.object(agent.client.chat.completions, "create", Mock(side_effect=[
            SimpleNamespace(choices=[SimpleNamespace(message=item)]) for item in messages
        ])) as completion, patch(
            "backend.ai.agent_client.execute_sql",
            new=AsyncMock(return_value={"success": True, "rows": [{"value": 1}]}),
        ) as execute:
            result = await agent.chat("查询当前数据库", [{"role": "user", "content": "确认连接"}])

        self.assertEqual(result["answer"], "查询返回 1。")
        self.assertEqual(result["rounds"], 1)
        self.assertTrue(result["tool_trace"][0]["success"])
        execute.assert_awaited_once_with(sql="SELECT 1 AS value")
        first_messages = completion.call_args_list[0].kwargs["messages"]
        self.assertIn("connected_via_live_connector", first_messages[0]["content"])
        self.assertIn("DISTRIBUTE BY SHARD(id) TO GROUP default_group", first_messages[0]["content"])
        self.assertIn('"sql_operation_approval_required": false', first_messages[0]["content"])
        self.assertIn('"chat_sql_can_execute_ddl_dml_admin_functions": true', first_messages[0]["content"])
        self.assertIn('"cancel_query_flag_scope":', first_messages[0]["content"])
        self.assertEqual(first_messages[1]["content"], "确认连接")

    async def test_fallback_separates_dn_lock_waits_from_prepared_transaction_finding(self):
        report = AIOpsAgent._fallback_diagnosis({
            "findings": [
                {
                    "check": "prepared_transaction_blocker",
                    "observed": "1 prepared transaction matches a coordinator wait",
                    "evidence": [{"transaction_id": "42", "gid": "gid-1", "database": "postgres"}],
                },
                {
                    "check": "data_node_lock_waits",
                    "evidence": {"waits": [{
                        "node_name": "dn0001", "waiting_pid": 200,
                        "locktype": "advisory", "blockers": [{"pid": 100}],
                    }]},
                },
            ]
        }, TimeoutError("model timed out"))

        root_cause = report["structured"]["root_cause"]
        self.assertIn("At least one coordinator lock wait", root_cause)
        self.assertIn("Separate data-node lock waits", report["structured"]["evidence"][-1])
        self.assertIn("dn0001 advisory wait", report["structured"]["evidence"][-1])

    async def test_tool_results_with_datetime_are_serialized_for_followup_turn(self):
        agent = AIOpsAgent(SimpleNamespace(
            DEEPSEEK_API_KEY="fixture-key",
            DEEPSEEK_API_BASE="https://example.invalid/v1",
            DEEPSEEK_TIMEOUT_SECONDS=1,
            DEEPSEEK_MODEL="fixture-model",
        ))
        self.addCleanup(agent.client.close)
        tool_call = SimpleNamespace(
            id="locks-1",
            function=SimpleNamespace(
                name="get_database_locks", arguments='{"include_granted":true}'
            ),
        )
        first = SimpleNamespace(content=None, tool_calls=[tool_call])
        final = SimpleNamespace(
            content='{"root_cause":"No blocking locks","risk_level":"low",'
                    '"evidence":[],"recommendations":[]}',
            tool_calls=[],
        )
        lock_result = {
            "collection_status": "success",
            "locks": [{"xact_start": datetime(2026, 11, 25, tzinfo=timezone.utc)}],
        }
        with patch.object(agent.client.chat.completions, "create", Mock(side_effect=[
            SimpleNamespace(choices=[SimpleNamespace(message=first)]),
            SimpleNamespace(choices=[SimpleNamespace(message=final)]),
        ])) as completion, patch(
            "backend.ai.agent_client.execute_get_database_locks",
            new=AsyncMock(return_value=lock_result),
        ):
            report = await agent.diagnose("Review locks", {})

        tool_message = completion.call_args_list[1].kwargs["messages"][-1]
        self.assertIn("2026-11-25 00:00:00+00:00", tool_message["content"])
        self.assertFalse(report["analysis_fallback"])
        self.assertTrue(report["tool_called"])

    async def test_model_can_search_again_after_reading_tool_results(self):
        agent = AIOpsAgent(SimpleNamespace(
            DEEPSEEK_API_KEY="fixture-key",
            DEEPSEEK_API_BASE="https://example.invalid/v1",
            DEEPSEEK_TIMEOUT_SECONDS=1,
            DEEPSEEK_MODEL="fixture-model",
        ))
        self.addCleanup(agent.client.close)

        def search_call(call_id, arguments):
            return SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(name="search_knowledge", arguments=arguments),
            )])

        messages = [
            search_call("first", '{"query":"pg_locks"}'),
            search_call("second", '{"query":"pg_prepared_xacts"}'),
            SimpleNamespace(content='{"root_cause":"Unknown","risk_level":"high",'
                                     '"evidence":[],"recommendations":[]}', tool_calls=[]),
        ]
        completion = Mock(side_effect=[
            SimpleNamespace(choices=[SimpleNamespace(message=message)]) for message in messages
        ])
        search = AsyncMock(side_effect=[
            {"results": [{"source_url": "https://example.invalid/locks"}]},
            {"results": [{"source_url": "https://example.invalid/prepared"}]},
        ])
        with patch.object(agent.client.chat.completions, "create", completion), patch(
            "backend.ai.agent_client.execute_search_knowledge", search
        ):
            report = await agent.diagnose("Review locks", {})
        self.assertEqual(search.await_count, 2)
        self.assertIn("tools", completion.call_args_list[1].kwargs)
        self.assertEqual(len(report["knowledge_refs"]), 2)
        self.assertEqual(report["tool_trace"], [
            {"round": 1, "tool": "search_knowledge", "hits": 1, "failed": False},
            {"round": 2, "tool": "search_knowledge", "hits": 1, "failed": False},
        ])
        self.assertEqual(report["structured"]["analysis_source"], "model")

    async def test_invalid_report_preserves_retrieved_references(self):
        await self._check_failed_report(
            [SimpleNamespace(message=SimpleNamespace(content='{"risk_level":"high"}'))],
            "InvalidDiagnosticReport",
        )

    async def test_empty_completion_preserves_retrieved_references(self):
        await self._check_failed_report([], "InvalidCompletionResponse")

    async def _check_failed_report(self, final_choices, expected_error):
        config = SimpleNamespace(
            DEEPSEEK_API_KEY="fixture-key",
            DEEPSEEK_API_BASE="https://example.invalid/v1",
            DEEPSEEK_TIMEOUT_SECONDS=1,
            DEEPSEEK_MODEL="fixture-model",
        )
        agent = AIOpsAgent(config)
        self.addCleanup(agent.client.close)
        tool_call = SimpleNamespace(
            id="search-1",
            function=SimpleNamespace(
                name="search_knowledge", arguments='{"query":"pg_locks"}'
            ),
        )
        first = SimpleNamespace(content=None, tool_calls=[tool_call])
        references = [{"source_url": "https://example.invalid/locks"}]
        context = {"locks": [{"query": "fixture SQL", "message": "fixture detail", "sqlstate": "55P03"}]}
        with patch.object(
            agent.client.chat.completions, "create",
            new=Mock(side_effect=[
                SimpleNamespace(choices=[SimpleNamespace(message=first)]),
                SimpleNamespace(choices=final_choices),
                SimpleNamespace(choices=final_choices),
            ]),
        ) as completion, patch(
            "backend.ai.agent_client.execute_search_knowledge",
            new=AsyncMock(return_value={"results": references}),
        ):
            report = await agent.diagnose("Review locks", context)

        for invocation in completion.call_args_list:
            prompt = invocation.kwargs["messages"][1]["content"]
            self.assertNotIn("fixture SQL", prompt)
            self.assertNotIn("fixture detail", prompt)
            self.assertIn("55P03", prompt)
        self.assertEqual(context["locks"][0]["query"], "fixture SQL")
        self.assertTrue(report["analysis_fallback"])
        self.assertTrue(report["tool_called"])
        self.assertEqual(report["ai_error"], expected_error)
        self.assertEqual(report["knowledge_refs"], references)
