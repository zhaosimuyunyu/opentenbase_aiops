import unittest

from backend.utils.sql_redaction_migration import sanitize_json_fields


class SqlRedactionMigrationTests(unittest.TestCase):
    def test_sanitizes_nested_query_fields_without_mutating_input(self):
        original = {
            "findings": [{
                "query": "SELECT * FROM users WHERE email='private@example.com'",
            }],
        }

        sanitized, changed = sanitize_json_fields(("evidence",), (original,))

        self.assertTrue(changed)
        self.assertEqual(
            sanitized["evidence"]["findings"][0]["query"],
            "SELECT * FROM users WHERE email='?'",
        )
        self.assertNotIn("private@example.com", str(sanitized))
        self.assertIn("private@example.com", str(original))

    def test_already_redacted_records_are_idempotent(self):
        sanitized, changed = sanitize_json_fields(
            ("evidence",),
            ({"query": "SELECT * FROM users WHERE email='?'", "query_redacted": True,
              "query_fingerprint": "a" * 64},),
        )

        self.assertFalse(changed)
        self.assertEqual(sanitized["evidence"]["query"], "SELECT * FROM users WHERE email='?'")
