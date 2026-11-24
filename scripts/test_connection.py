#!/usr/bin/env python3
"""Test OpenTenBase connection"""
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector
from backend.collectors.cluster import ClusterCollector


def main():
    """Test database connection and basic queries"""
    print("=" * 60)
    print("OpenTenBase Connection Test")
    print("=" * 60)

    # Initialize
    config = Config()
    print(f"\n📡 Connecting to {config.DB_HOST}:{config.DB_PORT}...")

    connector = OpenTenBaseConnector(config)

    # Test connection
    print("\n1️⃣ Testing connection...")
    status = connector.test_connection()

    if status['connected']:
        print("✅ Connection successful!")
        print(f"   - Version: {status.get('version', 'unknown')[:50]}...")
        print(f"   - Database: {status.get('database')}")
        print(f"   - User: {status.get('user')}")
    else:
        print("❌ Connection failed!")
        print(f"   - Error: {status.get('error')}")
        return 1

    # Test cluster collector
    print("\n2️⃣ Testing cluster collector...")
    collector = ClusterCollector(connector)
    result = collector.collect()

    if result['status'] == 'success':
        print("✅ Cluster data collected!")
        data = result['data']

        print(f"   - Nodes: {len(data.get('nodes', []))}")
        print(f"   - Total connections: {data.get('connections', {}).get('total', 0)}")
        print(f"   - Replication connections: {len(data.get('replication', []))}")

        nodes = data.get('nodes', [])
        if nodes:
            print("\n   Cluster Nodes:")
            for node in nodes:
                print(f"     - {node.get('node_name')}: "
                      f"{node.get('node_type')} @ "
                      f"{node.get('node_host')}:{node.get('node_port')}")
    else:
        print("❌ Collection failed!")
        print(f"   - Error: {result.get('error')}")
        return 1

    # Close connection
    connector.close()

    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
