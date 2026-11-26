import unittest

from backend.utils.audit_status import normalize_audit_record


class AuditStatusTests(unittest.TestCase):
    def test_legacy_readonly_audit_pending_status_is_presented_as_completed(self):
        record = {
            "audit_id": "audit-1",
            "audit_type": "readonly_health_audit",
            "status": "pending",
            "ai_analysis": {"structured": {"root_cause": "observed"}},
        }

        normalized = normalize_audit_record(record)

        self.assertEqual(normalized["status"], "completed")
        self.assertEqual(record["status"], "pending")

    def test_repair_and_unknown_status_values_are_preserved(self):
        for audit_type, status in (
            ("repair_request", "pending"),
            ("readonly_health_audit", "failed"),
        ):
            with self.subTest(audit_type=audit_type, status=status):
                normalized = normalize_audit_record({
                    "audit_type": audit_type,
                    "status": status,
                })
                self.assertEqual(normalized["status"], status)


if __name__ == "__main__":
    unittest.main()
