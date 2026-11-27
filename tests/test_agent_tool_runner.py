import unittest

from backend.ai.agent_client import _run_async_tool


class AgentToolRunnerTests(unittest.TestCase):
    def test_runs_synchronous_handler(self):
        result = _run_async_tool(lambda query: {"items": [query]}, query="lock")

        self.assertEqual(result, {"items": ["lock"]})

    def test_runs_asynchronous_handler(self):
        async def handler(query):
            return {"items": [query]}

        result = _run_async_tool(handler, query="lock")

        self.assertEqual(result, {"items": ["lock"]})


if __name__ == "__main__":
    unittest.main()
