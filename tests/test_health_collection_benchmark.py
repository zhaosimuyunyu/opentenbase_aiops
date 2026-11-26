import unittest

from scripts.benchmark_health_collection import _nearest_rank, _summarize


class HealthCollectionBenchmarkTests(unittest.TestCase):
    def test_nearest_rank_p95_uses_rank_definition(self):
        self.assertEqual(_nearest_rank(list(range(1, 11)), 0.95), 10)

    def test_summary_counts_partial_runs_and_check_failures(self):
        summary = _summarize([
            {"status": "success", "duration_ms": 10.0, "errors": []},
            {"status": "partial", "duration_ms": 20.0, "errors": ["locks", "storage"]},
            {"status": "partial", "duration_ms": 30.0, "errors": ["storage"]},
        ])

        self.assertEqual(summary["status_counts"], {"success": 1, "partial": 2})
        self.assertEqual(summary["errors_by_check"], {"locks": 1, "storage": 2})
        self.assertEqual(summary["median_ms"], 20.0)
        self.assertEqual(summary["p95_ms_nearest_rank"], 30.0)
        self.assertEqual(summary["max_ms"], 30.0)


if __name__ == "__main__":
    unittest.main()
