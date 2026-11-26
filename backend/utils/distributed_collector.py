"""Distributed multi-node data collection for OpenTenBase"""
import logging
import psycopg2
from copy import copy
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.extras import RealDictCursor
from ..collectors.readonly_health import CHECKS, _collection_error
from .config import Config
from .db_connector import OpenTenBaseConnector

logger = logging.getLogger(__name__)


class NodeConnection:
    """Represents a connection to a single OpenTenBase node"""

    def __init__(self, node_info: Dict[str, Any], config: Config):
        self.node_name = node_info['node_name']
        self.node_type = node_info['node_type']  # 'C', 'D', 'G'
        self.node_host = node_info['node_host']
        self.node_port = node_info['node_port']
        self.config = config
        self._connection = None

    def connect(self) -> bool:
        """Establish connection to this node"""
        try:
            # Keep per-node endpoints isolated from the shared coordinator settings.
            node_config = copy(self.config)
            node_config.DB_HOST = self.node_host
            node_config.DB_PORT = self.node_port
            node_config.DB_USER = self.config.DB_USER
            node_config.DB_PASSWORD = self.config.DB_PASSWORD
            node_config.DB_NAME = self.config.DB_NAME

            connector = OpenTenBaseConnector(node_config)
            self._connection = connector.connect()

            # Set read-only mode
            with self._connection.cursor() as cur:
                cur.execute("SET default_transaction_read_only = on")
                cur.execute("SET statement_timeout = '2500ms'")
                cur.execute("SET lock_timeout = '750ms'")
            self._connection.commit()

            return True
        except Exception as e:
            logger.warning(f"Failed to connect to {self.node_name} ({self.node_type}): {e}")
            return False

    def execute_query(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """Execute query on this node"""
        if not self._connection:
            raise ConnectionError(f"Not connected to {self.node_name}")

        try:
            with self._connection.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout = '2500ms'")
                cur.execute("SET LOCAL lock_timeout = '750ms'")
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Query failed on {self.node_name}: {e}")
            raise
        finally:
            self._connection.rollback()

    def close(self):
        """Close connection"""
        if self._connection and not self._connection.closed:
            try:
                self._connection.close()
            except Exception as e:
                logger.warning(f"Error closing connection to {self.node_name}: {e}")


class DistributedCollector:
    """Collect data from multiple OpenTenBase nodes in parallel"""

    def __init__(self, config: Config):
        self.config = config
        self.coordinator = OpenTenBaseConnector(config)

    ALLOWED_CHECKS = {
        *CHECKS.keys(),
    }

    def collect_diagnostics(self, node_filter=None, check_names=None):
        check_names = check_names or ["database_info", "connections", "replication", "locks"]
        invalid = set(check_names) - self.ALLOWED_CHECKS
        if invalid:
            raise ValueError(f"Unsupported diagnostic checks: {', '.join(sorted(invalid))}")
        nodes = self.get_cluster_nodes() or []
        if not nodes:
            return {"summary": {"total_nodes": 0, "success": 0, "failed": 1},
                    "results": [], "errors": [{"status": "error",
                                                  "error": "Coordinator node discovery failed or returned no CN/DN nodes"}]}
        if node_filter:
            if node_filter not in {"C", "D"}:
                raise ValueError("node_filter must be C or D")
            nodes = [node for node in nodes if node["node_type"] == node_filter]
        results, errors = [], []
        with ThreadPoolExecutor(max_workers=max(1, min(8, len(nodes)))) as executor:
            futures = {executor.submit(self._collect_node_checks, node, check_names): node for node in nodes}
            for future in as_completed(futures):
                node = futures[future]
                try:
                    result = future.result()
                    (errors if result["status"] == "error" else results).append(result)
                except Exception as error:
                    errors.append({"node_name": node["node_name"], "node_type": node["node_type"],
                                   "status": "error", "error": str(error)})
        results.sort(key=lambda row: (row["node_type"], row["node_name"]))
        errors.sort(key=lambda row: (row["node_type"], row["node_name"]))
        return {"summary": {"total_nodes": len(nodes), "success": len(results), "failed": len(errors)},
                "results": results, "errors": errors}

    def _collect_node_checks(self, node, check_names):
        connection = NodeConnection(node, self.config)
        if not connection.connect():
            return {"node_name": node["node_name"], "node_type": node["node_type"],
                    "status": "error", "checks": {}, "errors": {"connection": "Connection failed"}}
        checks, errors = {}, {}
        try:
            for name in check_names:
                try:
                    with connection._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                        cursor.execute("SET LOCAL statement_timeout = '2500ms'")
                        cursor.execute("SET LOCAL lock_timeout = '750ms'")
                        cursor.execute(CHECKS[name])
                        checks[name] = [dict(row) for row in cursor.fetchall()]
                    connection._connection.rollback()
                except Exception as error:
                    connection._connection.rollback()
                    errors[name] = _collection_error(error)
            return {"node_name": node["node_name"], "node_type": node["node_type"],
                    "status": "partial" if errors else "success", "checks": checks, "errors": errors}
        finally:
            connection.close()

    def get_cluster_nodes(self, include_gtm: bool = False) -> List[Dict[str, Any]]:
        """Get all nodes from pgxc_node"""
        sql = """
        SELECT
            node_name,
            node_type,
            node_host,
            node_port,
            nodeis_primary,
            nodeis_preferred
        FROM pgxc_node
        """

        if not include_gtm:
            sql += " WHERE node_type IN ('C', 'D')"

        sql += " ORDER BY node_type, node_name"

        try:
            return self.coordinator.execute_query(sql)
        except Exception as e:
            logger.error(f"Failed to get cluster nodes: {e}")
            return []

    def collect_from_all_nodes(
        self,
        sql: str,
        node_filter: Optional[str] = None,
        max_workers: int = 10
    ) -> Dict[str, Any]:
        """
        Execute the same query on all nodes in parallel

        Args:
            sql: SQL query to execute
            node_filter: 'C' for coordinators only, 'D' for datanodes only, None for both
            max_workers: Maximum concurrent connections

        Returns:
            {
                'summary': {'total_nodes': N, 'success': M, 'failed': K},
                'results': [
                    {
                        'node_name': 'cn0001',
                        'node_type': 'C',
                        'status': 'success',
                        'data': [...],
                        'row_count': N
                    },
                    ...
                ],
                'errors': [
                    {
                        'node_name': 'dn0001',
                        'node_type': 'D',
                        'error': 'connection refused'
                    },
                    ...
                ]
            }
        """
        nodes = self.get_cluster_nodes()

        if node_filter:
            nodes = [n for n in nodes if n['node_type'] == node_filter]

        if not nodes:
            return {
                'summary': {'total_nodes': 0, 'success': 0, 'failed': 0},
                'results': [],
                'errors': []
            }

        results = []
        errors = []

        def collect_from_node(node_info: Dict[str, Any]) -> Tuple[str, str, Any]:
            """Worker function to collect from one node"""
            node_conn = NodeConnection(node_info, self.config)
            node_name = node_info['node_name']
            node_type = node_info['node_type']

            try:
                if not node_conn.connect():
                    return (node_name, node_type, ConnectionError("Connection failed"))

                data = node_conn.execute_query(sql)
                return (node_name, node_type, data)
            except Exception as e:
                return (node_name, node_type, e)
            finally:
                node_conn.close()

        # Execute in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(collect_from_node, node): node
                for node in nodes
            }

            for future in as_completed(futures):
                node = futures[future]
                try:
                    node_name, node_type, result = future.result()

                    if isinstance(result, Exception):
                        errors.append({
                            'node_name': node_name,
                            'node_type': node_type,
                            'error': str(result),
                            'error_type': type(result).__name__
                        })
                    else:
                        results.append({
                            'node_name': node_name,
                            'node_type': node_type,
                            'node_host': node['node_host'],
                            'node_port': node['node_port'],
                            'status': 'success',
                            'data': result,
                            'row_count': len(result)
                        })
                except Exception as e:
                    logger.error(f"Unexpected error processing {node['node_name']}: {e}")
                    errors.append({
                        'node_name': node['node_name'],
                        'node_type': node['node_type'],
                        'error': str(e),
                        'error_type': 'UnexpectedError'
                    })

        return {
            'summary': {
                'total_nodes': len(nodes),
                'success': len(results),
                'failed': len(errors)
            },
            'results': results,
            'errors': errors
        }

    def collect_from_datanodes(self, sql: str) -> Dict[str, Any]:
        """Shortcut to collect from datanodes only"""
        return self.collect_from_all_nodes(sql, node_filter='D')

    def collect_from_coordinators(self, sql: str) -> Dict[str, Any]:
        """Shortcut to collect from coordinators only"""
        return self.collect_from_all_nodes(sql, node_filter='C')

    def aggregate_numeric_results(
        self,
        distributed_result: Dict[str, Any],
        sum_fields: Optional[List[str]] = None,
        avg_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Aggregate numeric fields across nodes

        Args:
            distributed_result: Result from collect_from_all_nodes
            sum_fields: Fields to sum across nodes
            avg_fields: Fields to average across nodes

        Returns:
            {
                'aggregated': {'field1': total, 'field2': avg, ...},
                'by_node': [...],
                'summary': {...}
            }
        """
        sum_fields = sum_fields or []
        avg_fields = avg_fields or []

        aggregated = {}
        by_node = []

        # Collect values from each node
        for result in distributed_result['results']:
            if result['status'] != 'success' or not result['data']:
                continue

            node_data = result['data'][0] if result['data'] else {}

            by_node.append({
                'node_name': result['node_name'],
                'node_type': result['node_type'],
                'values': node_data
            })

            # Sum fields
            for field in sum_fields:
                if field in node_data and node_data[field] is not None:
                    aggregated[field] = aggregated.get(field, 0) + node_data[field]

        # Average fields
        success_count = len(by_node)
        if success_count > 0:
            for field in avg_fields:
                total = sum(
                    node['values'].get(field, 0) or 0
                    for node in by_node
                    if field in node['values']
                )
                aggregated[f"{field}_avg"] = round(total / success_count, 2)

        return {
            'aggregated': aggregated,
            'by_node': by_node,
            'summary': distributed_result['summary'],
            'errors': distributed_result['errors']
        }
