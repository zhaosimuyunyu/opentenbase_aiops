import unittest
from unittest.mock import MagicMock, patch

from backend.engines.sql_audit import audit_sql


class SqlAuditTests(unittest.TestCase):
    def test_destructive_rules_are_critical(self):
        result = audit_sql("DELETE FROM public.orders")
        self.assertEqual(result["risk_level"], "critical")
        self.assertIn("delete_without_where", [item["rule"] for item in result["findings"]])

    def test_safe_select_runs_read_only_explain(self):
        connector = MagicMock()
        connection = connector.return_value.connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ({"QUERY PLAN": [{"Plan": {"Node Type": "Seq Scan"}}]},)
        with patch("backend.engines.sql_audit.OpenTenBaseConnector", connector):
            result = audit_sql("SELECT id FROM public.orders")
        self.assertIsNotNone(result["explain"])
        self.assertTrue(connection.rollback.called)
        self.assertEqual(cursor.execute.call_count, 3)

    def test_multiple_statements_are_rejected(self):
        with self.assertRaises(ValueError):
            audit_sql("SELECT 1; DROP TABLE public.orders")

    def test_semicolon_inside_string_is_not_a_second_statement(self):
        result = audit_sql("SELECT ';' AS punctuation", explain=False)
        self.assertEqual(result["risk_level"], "low")

    def test_high_risk_function_does_not_run_explain(self):
        with patch("backend.engines.sql_audit.OpenTenBaseConnector") as connector:
            result = audit_sql("SELECT pg_terminate_backend(42)", explain=True)
        self.assertEqual(result["risk_level"], "critical")
        connector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
