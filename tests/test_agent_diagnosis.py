import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.ai.agent_client import AIOpsAgent


class AgentDiagnosisTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_report_preserves_retrieved_references(self):
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
        final = SimpleNamespace(content='{"risk_level":"high"}')
        references = [{"source_url": "https://example.invalid/locks"}]
        with patch.object(
            agent.client.chat.completions, "create",
            new=Mock(side_effect=[
                SimpleNamespace(choices=[SimpleNamespace(message=first)]),
                SimpleNamespace(choices=[SimpleNamespace(message=final)]),
            ]),
        ), patch(
            "backend.ai.agent_client.execute_search_knowledge",
            new=AsyncMock(return_value={"results": references}),
        ):
            report = await agent.diagnose("Review locks", {})

        self.assertTrue(report["analysis_fallback"])
        self.assertTrue(report["tool_called"])
        self.assertEqual(report["ai_error"], "InvalidDiagnosticReport")
        self.assertEqual(report["knowledge_refs"], references)
