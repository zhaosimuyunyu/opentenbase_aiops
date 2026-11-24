import unittest
from unittest.mock import MagicMock, patch

from backend.collectors.readonly_health import ReadonlyHealthCollector


class NodeConnectivityTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
