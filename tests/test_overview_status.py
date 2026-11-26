import unittest

from frontend.cluster_status import cluster_health_banner


class OverviewStatusTests(unittest.TestCase):
    def test_partial_collection_does_not_claim_nodes_are_unreachable(self):
        connectivity = [
            {"node_name": name, "status": "reachable"}
            for name in ("cn0001", "dn0001", "dn0002", "gtm0001")
        ]

        banner = cluster_health_banner("partial", connectivity, 4, 3)

        self.assertEqual(banner[2], "集群状态采集不完整")
        self.assertIn("所有节点网络可达", banner[3])

    def test_unreachable_node_is_reported_separately(self):
        banner = cluster_health_banner("partial", [
            {"node_name": "cn0001", "status": "reachable"},
            {"node_name": "dn0001", "status": "unreachable"},
        ], 2, 1)

        self.assertEqual(banner[2], "集群部分节点不可达")
        self.assertIn("dn0001", banner[3])

    def test_missing_connectivity_results_are_not_marked_healthy(self):
        banner = cluster_health_banner("success", [
            {"node_name": "cn0001", "status": "reachable"},
        ], 2, 0)

        self.assertEqual(banner[2], "节点可达性未知")

    def test_empty_topology_is_not_marked_healthy(self):
        banner = cluster_health_banner("success", [], 0, 0)

        self.assertEqual(banner[2], "未发现注册节点")


if __name__ == "__main__":
    unittest.main()
