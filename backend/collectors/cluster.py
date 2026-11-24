"""Cluster status collector"""
from typing import Dict, Any, List
from .base import BaseCollector
from ..utils.logger import setup_logger
from .readonly_health import CHECKS, ReadonlyHealthCollector

logger = setup_logger(__name__)


class ClusterCollector(BaseCollector):
    """Collect OpenTenBase cluster status information"""

    def collect(self) -> Dict[str, Any]:
        """Collect all cluster information"""
        self.errors = []
        try:
            nodes = self.get_nodes()
            node_connectivity = ReadonlyHealthCollector._probe_node_connectivity(nodes)
            for node in node_connectivity:
                if node['status'] == 'unreachable':
                    self._record_error(
                        f"node_connectivity:{node['node_name']}",
                        ConnectionError(node['error'] or 'Node endpoint is unreachable'),
                    )
            return self._create_result(
                status='success',
                data={
                    'nodes': nodes,
                    'node_connectivity': node_connectivity,
                    'connections': self.get_connections(),
                    'replication': self.get_replication_status(),
                    'database_info': self.get_database_info(),
                    'distributed_info': self.get_distributed_info()
                }
            )
        except Exception as e:
            self._record_error('cluster', e)
            logger.error(f"Cluster collection failed: {e}")
            return self._create_result(status='error', error=str(e))

    def get_nodes(self) -> List[Dict[str, Any]]:
        """Get cluster nodes information"""
        sql = """
        SELECT
            node_name,
            node_type,
            node_host,
            node_port,
            nodeis_primary,
            nodeis_preferred
        FROM pgxc_node
        ORDER BY node_type, node_name;
        """
        try:
            result = self.db.execute_query(sql)
            return result if result else []
        except Exception as e:
            self._record_error('nodes', e)
            logger.error(f"Failed to get nodes: {e}")
            return []

    def get_connections(self) -> Dict[str, Any]:
        """Get connection statistics"""
        try:
            connections = self.db.execute_query(CHECKS['connections'])
            max_conn = self.db.execute_query(CHECKS['max_connections'], fetch_one=True)

            total = sum(c['connection_count'] for c in connections) if connections else 0
            max_connections = max_conn['max_connections'] if max_conn else None

            return {
                'by_database': connections or [],
                'total': total,
                'max_connections': max_connections,
                'scope': 'connected_cn',
                'usage_percent': round(total / max_connections * 100, 2) if max_connections else None,
            }
        except Exception as e:
            self._record_error('connections', e)
            logger.error(f"Failed to get connections: {e}")
            return {'error': str(e)}

    def get_replication_status(self) -> List[Dict[str, Any]]:
        """Get replication status"""
        sql = """
        SELECT
            pid,
            usename,
            application_name,
            client_addr,
            state,
            sync_state,
            replay_lag
        FROM pg_stat_replication;
        """
        try:
            result = self.db.execute_query(sql)
            return result if result else []
        except Exception as e:
            self._record_error('replication', e)
            logger.error(f"Failed to get replication status: {e}")
            return []

    def get_database_info(self) -> Dict[str, Any]:
        """Get basic database information"""
        sql = """
        SELECT
            version() as version,
            current_database() as database,
            current_user as user,
            pg_is_in_recovery() as is_replica;
        """
        try:
            result = self.db.execute_query(sql, fetch_one=True)

            # Get data directory
            data_dir_sql = "SHOW data_directory;"
            data_dir = self.db.execute_query(data_dir_sql, fetch_one=True)

            if result:
                result['data_directory'] = data_dir.get('data_directory') if data_dir else 'unknown'

            return result or {}
        except Exception as e:
            self._record_error('database_info', e)
            logger.error(f"Failed to get database info: {e}")
            return {'error': str(e)}

    def get_distributed_info(self) -> Dict[str, Any]:
        """Get OpenTenBase distributed information"""
        sql = """
        SELECT
            n.nspname AS schemaname,
            c.relname AS tablename,
            pclocatortype as distribution_type,
            x.nodeoids AS nodeids
        FROM pgxc_class x
        JOIN pg_class c ON c.oid = x.pcrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
        LIMIT 50;
        """
        try:
            tables = self.db.execute_query(sql)

            # Count by distribution type
            type_counts = {}
            if tables:
                for table in tables:
                    dist_type = table.get('distribution_type', 'unknown')
                    type_counts[dist_type] = type_counts.get(dist_type, 0) + 1

            return {
                'tables': tables or [],
                'distribution_summary': type_counts
            }
        except Exception as e:
            self._record_error('distributed_info', e)
            logger.error(f"Failed to get distributed info: {e}")
            return {'error': str(e)}
