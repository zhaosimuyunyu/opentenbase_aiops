import unittest
from unittest.mock import patch

from scripts.benchmark_health_collection import _collect, _nearest_rank, _summarize


class HealthCollectionBenchmarkTests(unittest.TestCase):
    def test_nearest_rank_p95_uses_rank_definition(self):
        self.assertEqual(_nearest_rank(list(range(1, 11)), 0.95), 10)

    def test_summary_counts_partial_runs_and_check_failures(self):
        summary = _summarize([
            {"status": "success", "duration_ms": 10.0, "errors": {}},
            {"status": "partial", "duration_ms": 20.0, "errors": {
                "locks": {"type": "LockNotAvailable", "sqlstate": "55P03"},
                "data_node_stats:dn2": {"type": "OperationalError", "sqlstate": "08006"},
            }},
            {"status": "partial", "duration_ms": 30.0, "errors": {
                "storage": {"type": "LockNotAvailable", "sqlstate": "55P03"},
            }},
        ])

        self.assertEqual(summary["status_counts"], {"success": 1, "partial": 2})
        self.assertEqual(summary["errors_by_check"], {
            "locks": 1, "data_node_stats:dn2": 1, "storage": 1,
        })
        self.assertEqual(summary["errors_by_sqlstate"], {"55P03": 2, "08006": 1})
        self.assertEqual(summary["median_ms"], 20.0)
        self.assertEqual(summary["p95_ms_nearest_rank"], 30.0)
        self.assertEqual(summary["max_ms"], 30.0)
        self.assertEqual(summary["error_count"], 3)

    @patch("scripts.benchmark_health_collection.ReadonlyHealthCollector")
    def test_sample_reports_error_type_and_sqlstate_without_raw_message(self, collector_type):
        collector_type.return_value.collect.return_value = {
            "status": "partial",
            "collection_duration_ms": 25.0,
            "errors": {
                "data_node_stats:dn2": {
                    "type": "LockNotAvailable",
                    "sqlstate": "55P03",
                    "message": "sensitive query text should not be copied",
                },
            },
        }

        sample = _collect(object(), 1)

        self.assertEqual(sample["errors"], {
            "data_node_stats:dn2": {"type": "LockNotAvailable", "sqlstate": "55P03"},
        })
        self.assertNotIn("sensitive query text", str(sample))


if __name__ == "__main__":
    unittest.main()
