import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.collectors.performance import PerformanceCollector


class PerformanceCollectorTests(unittest.TestCase):
    def make_collector(self):
        config = SimpleNamespace(
            AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS=2500,
            AIOPS_COLLECTION_LOCK_TIMEOUT_MS=750,
        )
        connector = MagicMock()
        connector.execute_query.return_value = []
        collector = PerformanceCollector(connector, config)
        cursor = connector.get_cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        return collector, connector, cursor

    def test_lock_collection_runs_only_lock_query_with_bounded_timeouts(self):
        collector, connector, cursor = self.make_collector()

        result = collector.collect_locks()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["locks"], [])
        self.assertEqual(result["data"]["summary"]["blocked_count"], 0)
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(connector.get_cursor.call_count, 1)
        self.assertIn("FROM pg_locks", cursor.execute.call_args_list[1].args[0])
        self.assertEqual(
            cursor.execute.call_args_list[0].args[1],
            ("2500ms", "750ms"),
        )

    def test_lock_collection_does_not_report_query_failure_as_no_locks(self):
        collector, connector, cursor = self.make_collector()
        cursor.execute.side_effect = [None, RuntimeError("lock timeout")]

        result = collector.collect_locks()

        self.assertEqual(result["status"], "partial")
        self.assertIn("lock timeout", result["errors"][0]["error"])
        self.assertEqual(result["data"]["locks"], {})

    def test_long_query_threshold_is_parameterized_and_clamped(self):
        collector, connector, cursor = self.make_collector()
        cursor.fetchall.return_value = [{
            "pid": 42, "query": "SELECT * FROM users WHERE id=9917",
        }]

        result = collector.collect_long_queries(threshold_seconds=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(cursor.execute.call_args_list[1].args[1], (1,))
        self.assertIn("pg_stat_activity", cursor.execute.call_args_list[1].args[0])
        query = result["data"]["queries"][0]
        self.assertEqual(query["query"], "SELECT * FROM users WHERE id=?")
        self.assertNotIn("9917", query["query"])
        self.assertEqual(len(query["query_fingerprint"]), 64)

    def test_table_statistics_limit_is_bounded(self):
        collector, connector, cursor = self.make_collector()

        result = collector.collect_table_stats(limit=50000)

        self.assertEqual(result["status"], "success")
        self.assertEqual(cursor.execute.call_args_list[1].args[1], (500,))
        self.assertIn("pg_stat_user_tables", cursor.execute.call_args_list[1].args[0])

    def test_distributed_table_statistics_use_direct_data_node_collection(self):
        collector, connector, cursor = self.make_collector()
        connector.execute_query.return_value = [{"node_name": "dn0001"}]
        cursor.fetchall.return_value = [{"tablename": "orders", "n_live_tup": 25}]

        result = collector.collect_table_stats(limit=50000)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["tables"], [
            {"node_name": "dn0001", "tablename": "orders", "n_live_tup": 25},
        ])
        direct_query = cursor.execute.call_args_list[1]
        self.assertEqual(direct_query.args[0].seq[1].string, "dn0001")
        self.assertIn("LIMIT 500", direct_query.args[1][0])


if __name__ == "__main__":
    unittest.main()
