import unittest

from backend.utils.readiness import build_readiness


class ReadinessTests(unittest.TestCase):
    def test_all_required_databases_must_be_connected(self):
        result = build_readiness(
            {"connected": True, "version": "OpenTenBase"},
            {"connected": True},
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["api"], "healthy")
        self.assertIn("opentenbase", result["components"])
        self.assertIn("metadata_database", result["components"])

    def test_missing_database_dependency_marks_service_degraded(self):
        result = build_readiness(
            {"connected": True},
            {"connected": False, "error": "OperationalError"},
        )

        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(result["api"], "degraded")
        self.assertEqual(result["components"]["metadata_database"]["error"], "OperationalError")

    def test_missing_optional_ai_capability_does_not_hide_database_readiness(self):
        result = build_readiness(
            {"connected": True},
            {"connected": True},
            capabilities={"ai_analysis": {"configured": False, "model": None}},
        )

        self.assertEqual(result["status"], "ready")
        self.assertFalse(result["capabilities"]["ai_analysis"]["configured"])
        self.assertIsNone(result["capabilities"]["ai_analysis"]["model"])


if __name__ == "__main__":
    unittest.main()
