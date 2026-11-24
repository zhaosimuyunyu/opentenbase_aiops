import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from backend.collectors.readonly_health import CHECKS, ReadonlyHealthCollector
from backend.ai.agent_client import AIOpsAgent


class NodeConnectivityTests(unittest.TestCase):
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
            collector, "_collect_data_node_stats", side_effect=[([], limits), (targeted, {})]
        ) as stats:
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
