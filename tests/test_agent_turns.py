import unittest
from unittest.mock import MagicMock, patch

from backend.engines.agent_turns import AgentTurnStore


class AgentTurnStoreTests(unittest.TestCase):
    def test_start_keeps_existing_user_message_and_creates_running_turn(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            None,
            ("session title", [{"role": "user", "content": "inspect", "turn_id": "turn-1"}]),
        ]
        with patch("backend.engines.agent_turns.OperationsStore", return_value=store):
            result = AgentTurnStore().start("session-1", "turn-1", "inspect")

        self.assertEqual(result, {
            "turn_id": "turn-1", "status": "running", "created": True,
        })
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("UPDATE agent_sessions" in statement for statement in statements))
        self.assertTrue(any("INSERT INTO agent_turns" in statement for statement in statements))
        updated_messages = cursor.execute.call_args_list[-2].args[1][1].adapted
        self.assertEqual(len(updated_messages), 1)
        store.close.assert_called_once()

    def test_start_returns_existing_turn_without_adding_another(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("running",)
        with patch("backend.engines.agent_turns.OperationsStore", return_value=store):
            result = AgentTurnStore().start("session-1", "turn-1", "inspect")

        self.assertEqual(result, {
            "turn_id": "turn-1", "status": "running", "created": False,
        })
        self.assertEqual(cursor.execute.call_count, 3)

    def test_complete_persists_answer_and_session_message_in_one_transaction(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("session-1", "running")
        with patch("backend.engines.agent_turns.OperationsStore", return_value=store):
            completed = AgentTurnStore().complete("turn-1", {
                "answer": "The cluster is online.",
                "tool_trace": [{"tool": "get_cluster_diagnostics"}],
                "rounds": 1,
            })

        self.assertTrue(completed)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("UPDATE agent_sessions" in statement for statement in statements))
        self.assertTrue(any("SET status='completed'" in statement for statement in statements))
        assistant_messages = cursor.execute.call_args_list[-2].args[1][0].adapted
        self.assertEqual(assistant_messages[0]["turn_id"], "turn-1")
        self.assertEqual(assistant_messages[0]["content"], "The cluster is online.")

    def test_restart_marks_running_turns_interrupted(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("agent_turns",)
        cursor.rowcount = 2
        with patch("backend.engines.agent_turns.OperationsStore", return_value=store):
            count = AgentTurnStore().mark_interrupted()

        self.assertEqual(count, 2)
        self.assertIn("SET status='interrupted'", cursor.execute.call_args.args[0])
        self.assertIn("WHERE status='running'", cursor.execute.call_args.args[0])

    def test_deleting_session_also_deletes_its_agent_turns(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("agent_turns",)
        with patch("backend.engines.agent_turns.OperationsStore", return_value=store):
            AgentTurnStore().delete_session("session-1")

        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("DELETE FROM agent_turns" in statement for statement in statements))
        self.assertTrue(any("DELETE FROM agent_sessions" in statement for statement in statements))


if __name__ == "__main__":
    unittest.main()
