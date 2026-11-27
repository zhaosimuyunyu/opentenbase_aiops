import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.utils.sql_redaction import redact_query_data, redact_sql_literals


class SqlRedactionTests(unittest.TestCase):
    def test_redacts_nested_query_evidence_and_preserves_original(self):
        raw = "SELECT email FROM users WHERE tenant_id=881 AND email='private@example.com'"
        evidence = {"performance": {"long_running_queries": [{"query": raw}]}}

        sanitized = redact_query_data(evidence)
        row = sanitized["performance"]["long_running_queries"][0]

        self.assertEqual(row["query"], "SELECT email FROM users WHERE tenant_id=? AND email='?'")
        self.assertTrue(row["query_redacted"])
        self.assertEqual(
            row["query_fingerprint"], hashlib.sha256(row["query"].encode()).hexdigest()
        )
        self.assertNotIn("private@example.com", str(sanitized))
        self.assertEqual(evidence["performance"]["long_running_queries"][0]["query"], raw)

    def test_parser_failure_returns_safe_placeholder_with_fingerprint(self):
        raw = "unparseable secret=private-value"
        with patch("backend.utils.sql_redaction.sqlparse.parse", side_effect=ValueError):
            redacted, fingerprint = redact_sql_literals(raw)

        self.assertNotIn("private-value", redacted)
        self.assertEqual(
            fingerprint,
            hashlib.sha256("[SQL redacted because tokenization failed]".encode()).hexdigest(),
        )


class LockToolRedactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_lock_tool_returns_only_redacted_query_literals(self):
        from backend.tools.lock_audit_tool import execute_get_database_locks

        database = MagicMock()
        database.config = SimpleNamespace(AIOPS_SLOW_QUERY_REDACT_LITERALS=True)
        cursor = database.get_cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{
            "pid": 42,
            "query": "UPDATE users SET email='private@example.com' WHERE id=7791",
            "granted": False,
        }]
        with patch(
            "backend.tools.lock_audit_tool.OpenTenBaseConnector",
            return_value=database,
        ):
            result = await execute_get_database_locks()

        row = result["locks"][0]
        self.assertEqual(
            row["query"], "UPDATE users SET email='?' WHERE id=?"
        )
        self.assertNotIn("private@example.com", str(result))
        self.assertNotIn("7791", str(result))
        self.assertEqual(len(row["query_fingerprint"]), 64)
        self.assertTrue(row["query_redacted"])
        database.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
