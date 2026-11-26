"""Read diagnostic snapshots from the registered OpenTenBase CN and DN nodes."""
import socket

from ..collectors.readonly_health import CHECKS
from ..utils.config import Config
from ..utils.distributed_collector import DistributedCollector


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_cluster_diagnostics",
        "description": (
            "Discover the connected OpenTenBase CN/DN topology and collect live per-node "
            "database status, connections, replication, locks, prepared transactions, long "
            "queries, table/index statistics, storage and key settings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "node_filter": {"type": "string", "enum": ["C", "D", "G"]},
                "checks": {"type": "array", "items": {"type": "string", "enum": sorted(CHECKS)}},
            },
        },
    },
}


async def execute_cluster_diagnostics(node_filter=None, checks=None):
    collector = DistributedCollector(Config())
    try:
        topology = collector.get_cluster_nodes(include_gtm=True)
        selected = topology
        if node_filter:
            selected = [node for node in topology if node.get("node_type") == node_filter]
        gtms = [node for node in selected if node.get("node_type") == "G"]
        for node in gtms:
            try:
                with socket.create_connection(
                    (node["node_host"], int(node["node_port"])), timeout=2
                ):
                    node["endpoint_status"] = "reachable"
            except OSError as error:
                node["endpoint_status"] = "unreachable"
                node["endpoint_error"] = str(error)
        if node_filter == "G":
            reachable = sum(node.get("endpoint_status") == "reachable" for node in gtms)
            diagnostics = {"summary": {"total_nodes": len(gtms), "success": reachable,
                                        "failed": len(gtms) - reachable},
                           "results": [], "errors": [],
                           "note": "GTM uses its native protocol. Only TCP reachability is probed."}
        else:
            diagnostics = collector.collect_diagnostics(node_filter, checks)
        return {"topology": selected, "diagnostics": diagnostics}
    finally:
        collector.coordinator.close()
