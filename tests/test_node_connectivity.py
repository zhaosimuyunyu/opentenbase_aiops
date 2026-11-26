import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from backend.collectors.readonly_health import CHECKS, ReadonlyHealthCollector
from backend.ai.agent_client import AIOpsAgent
from backend.utils.distributed_collector import DistributedCollector


class NodeConnectivityTests(unittest.TestCase):
    def test_distributed_check_whitelist_matches_registered_queries(self):
        self.assertLessEqual(DistributedCollector.ALLOWED_CHECKS, set(CHECKS))
        self.assertIn("key_guc", CHECKS)
        self.assertIn("storage", CHECKS)
        self.assertIn("data_node_lock_blockers", CHECKS)
        self.assertIn("long_running_queries", CHECKS)
        self.assertIn("application_name", CHECKS["long_running_queries"])

    def test_distributed_collect_rejects_arbitrary_sql(self):
        collector = DistributedCollector(SimpleNamespace())
        with self.assertRaisesRegex(ValueError, "Unsupported diagnostic checks"):
            collector.collect_diagnostics(check_names=["SELECT 1"])

    def test_distributed_collect_returns_structured_error_when_node_discovery_fails(self):
        collector = DistributedCollector(SimpleNamespace())
        with patch.object(collector, "get_cluster_nodes", return_value=[]):
            result = collector.collect_diagnostics(check_names=["key_guc"])
        self.assertEqual(result["summary"], {"total_nodes": 0, "success": 0, "failed": 1})
        self.assertEqual(result["errors"][0]["status"], "error")

    def test_distributed_collect_preserves_partial_node_failures(self):
        collector = DistributedCollector(SimpleNamespace())
        nodes = [
            {"node_name": "cn0001", "node_type": "C"},
            {"node_name": "dn0001", "node_type": "D"},
        ]
        node_results = {
            "cn0001": {"node_name": "cn0001", "node_type": "C", "status": "partial",
                       "checks": {"key_guc": []}, "errors": {"storage": {"message": "unsupported"}}},
            "dn0001": {"node_name": "dn0001", "node_type": "D", "status": "error",
                       "checks": {}, "errors": {"connection": "refused"}},
        }
        with patch.object(collector, "get_cluster_nodes", return_value=nodes), patch.object(
            collector, "_collect_node_checks", side_effect=lambda node, checks: node_results[node["node_name"]]
        ):
            result = collector.collect_diagnostics(check_names=["key_guc", "storage"])
        self.assertEqual(result["summary"], {"total_nodes": 2, "success": 1, "failed": 1})
        self.assertEqual(result["results"][0]["status"], "partial")
        self.assertEqual(result["errors"][0]["node_name"], "dn0001")

    def test_each_distributed_check_sets_readonly_timeouts(self):
        collector = DistributedCollector(SimpleNamespace())
        node = {"node_name": "dn0001", "node_type": "D", "node_host": "dn1", "node_port": 11006}
        connection = MagicMock()
        connection.connect.return_value = True
        connection._connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        with patch("backend.utils.distributed_collector.NodeConnection", return_value=connection):
            result = collector._collect_node_checks(node, ["key_guc"])
        self.assertEqual(result["status"], "success")
        calls = connection._connection.cursor.return_value.__enter__.return_value.execute.call_args_list
        self.assertEqual(calls[0].args, ("SET LOCAL statement_timeout = '2500ms'",))
        self.assertEqual(calls[1].args, ("SET LOCAL lock_timeout = '750ms'",))

    def test_official_pg_unlock_probe_is_read_only(self):
        self.assertIn("pg_unlock_check_dependency", CHECKS["pg_unlock_diagnostics"])
        self.assertIn("pg_unlock_check_deadlock", CHECKS["pg_unlock_diagnostics"])
        self.assertNotIn("pg_unlock_execute", CHECKS["pg_unlock_diagnostics"])
        self.assertNotIn("public.pg_unlock_", CHECKS["pg_unlock_diagnostics"])
        self.assertIn("to_regprocedure('pg_unlock_check_dependency()')", CHECKS["pg_unlock_diagnostics"])

    def test_readonly_health_collector_uses_configured_query_timeouts(self):
        collector = ReadonlyHealthCollector(SimpleNamespace(
            AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS=6000,
            AIOPS_COLLECTION_LOCK_TIMEOUT_MS=1800,
        ))
        cursor = MagicMock()

        collector._set_query_timeouts(cursor)

        self.assertEqual(cursor.execute.call_args.args[1], ("6000ms", "1800ms"))

    def test_readonly_health_collector_allows_explicit_timeout_overrides(self):
        collector = ReadonlyHealthCollector(
            SimpleNamespace(
                AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS=6000,
                AIOPS_COLLECTION_LOCK_TIMEOUT_MS=1800,
            ),
            statement_timeout_ms=4000,
            lock_timeout_ms=1200,
        )
        cursor = MagicMock()

        collector._set_query_timeouts(cursor)

        self.assertEqual(cursor.execute.call_args.args[1], ("4000ms", "1200ms"))

    def test_lock_collection_filters_invalid_open_tenbase_blocker_pid(self):
        self.assertIn("array_remove(pg_blocking_pids(l.pid), 0)", CHECKS["locks"])

    def test_bulk_limit_preserves_partial_status_and_collects_configured_table(self):
        target = "public.orders"
        collector = ReadonlyHealthCollector(SimpleNamespace(AIOPS_AUTO_AUDIT_TARGETS=[target]))
        nodes = [
            {"node_name": "dn0001", "node_type": "D"},
            {"node_name": "dn0002", "node_type": "D"},
        ]
        limits = {f"data_node_stats:{node['node_name']}": {"type": "CollectionLimit"} for node in nodes}
        targeted = [{"schemaname": "public", "tablename": "orders", "nodes": nodes}]
        with patch("backend.collectors.readonly_health.OpenTenBaseConnector") as connector, patch.object(
            collector, "_probe_node_connectivity", return_value=[]
        ), patch.object(
            collector, "_collect_data_node_prepared_xacts", return_value=([], {})
        ), patch.object(
            collector, "_collect_data_node_lock_blockers", return_value=([], {})
        ), patch.object(
            collector, "_collect_data_node_long_queries", return_value=([], {})
        ), patch(
            "backend.collectors.readonly_health.SlowQueryLogCollector"
        ) as log_collector, patch.object(
            collector, "_collect_data_node_stats", side_effect=[([], limits), (targeted, {})]
        ) as stats:
            log_collector.return_value.collect.return_value = ([], {})
            connection = connector.return_value.connect.return_value
            cursor = connection.cursor.return_value.__enter__.return_value
            cursor.fetchall.side_effect = [nodes if name == "nodes" else [] for name in CHECKS]
            snapshot = collector.collect()

        self.assertEqual(stats.call_args_list, [
            call(connection, nodes, table=None), call(connection, nodes, table=target),
        ])
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["errors"], limits)
        self.assertEqual(snapshot["checks"]["data_node_stats_fallback"], {
            target: {"tables": targeted, "errors": {}},
        })

    @patch("backend.collectors.readonly_health.socket.create_connection")
    def test_reports_reachable_and_unreachable_registered_nodes(self, connect):
        connect.side_effect = [MagicMock(), OSError("connection refused")]
        nodes = [
            {"node_name": "dn0001", "node_type": "D", "node_host": "10.0.0.1", "node_port": 11006},
            {"node_name": "dn0002", "node_type": "D", "node_host": "10.0.0.2", "node_port": 11006},
        ]

        results = ReadonlyHealthCollector._probe_node_connectivity(nodes)

        self.assertEqual([item["status"] for item in results], ["reachable", "unreachable"])
        self.assertEqual(results[1]["node_name"], "dn0002")
        self.assertIn("connection refused", results[1]["error"])
        self.assertEqual(connect.call_count, 2)

    def test_reports_missing_endpoint_as_unknown(self):
        results = ReadonlyHealthCollector._probe_node_connectivity([
            {"node_name": "dn0001", "node_type": "D", "node_host": None, "node_port": None},
        ])

        self.assertEqual(results[0]["status"], "unknown")

    def test_aggregates_table_statistics_across_data_nodes(self):
        collector = ReadonlyHealthCollector()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [(name,) for name in (
            "schemaname", "relname", "n_live_tup", "n_mod_since_analyze", "last_analyze"
        )]
        cursor.fetchall.side_effect = [
            [("app", "orders", 700, 200, "2026-11-20T00:00:00Z")],
            [("app", "orders", 500, 300, "2026-11-21T00:00:00Z")],
        ]
        nodes = [
            {"node_name": "dn0001", "node_type": "D"},
            {"node_name": "cn0001", "node_type": "C"},
            {"node_name": "dn0002", "node_type": "D"},
        ]

        tables, errors = collector._collect_data_node_stats(connection, nodes)

        self.assertEqual(errors, {})
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["live_tuples"], 1200)
        self.assertEqual(tables[0]["modifications_since_analyze"], 500)
        self.assertEqual([node["node_name"] for node in tables[0]["nodes"]], ["dn0001", "dn0002"])

    def test_preserves_prepared_transaction_participants_by_data_node(self):
        collector = ReadonlyHealthCollector()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [{"transaction_id": "11576", "gid": "g-1", "owner": "dbuser"}],
            [{"transaction_id": "11457", "gid": "g-1", "owner": "dbuser"}],
        ]

        transactions, errors = collector._collect_data_node_prepared_xacts(
            connection,
            [
                {"node_name": "dn0001", "node_type": "D"},
                {"node_name": "cn0001", "node_type": "C"},
                {"node_name": "dn0002", "node_type": "D"},
            ],
        )

        self.assertEqual(errors, {})
        self.assertEqual([item["node_name"] for item in transactions], ["dn0001", "dn0002"])
        self.assertEqual([item["transaction_id"] for item in transactions], ["11576", "11457"])

    def test_fallback_diagnosis_names_each_prepared_transaction_participant(self):
        context = {
            "findings": [{
                "check": "prepared_transaction_blocker",
                "observed": "One prepared transaction blocks two waiters",
                "evidence": [{
                    "transaction_id": "21973",
                    "gid": "g-1",
                    "owner": "dbuser",
                    "database": "postgres",
                    "data_node_participants": [
                        {"node_name": "dn0001", "transaction_id": "11576", "gid": "g-1"},
                        {"node_name": "dn0002", "transaction_id": "11457", "gid": "g-1"},
                    ],
                }],
            }],
        }

        result = AIOpsAgent._fallback_diagnosis(context, "timeout")

        self.assertIn("dn0001", result["structured"]["evidence"][-2])
        self.assertIn("11576", result["structured"]["evidence"][-2])
        self.assertIn("dn0002", result["structured"]["evidence"][-1])
        self.assertIn("11457", result["structured"]["evidence"][-1])


if __name__ == "__main__":
    unittest.main()
