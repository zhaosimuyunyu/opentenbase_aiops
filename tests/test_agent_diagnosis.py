import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.ai.agent_client import AIOpsAgent


class AgentDiagnosisTests(unittest.IsolatedAsyncioTestCase):
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
