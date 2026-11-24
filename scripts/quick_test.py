#!/usr/bin/env python3
"""Quick local test without Docker"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector
from backend.collectors.cluster import ClusterCollector
from backend.ai.llm_client import DeepSeekClient

print("=" * 60)
print("OpenTenBase AIOps - Quick Test")
print("=" * 60)

# Test 1: Configuration
print("\n✅ Step 1: Loading configuration...")
config = Config()
print(f"   DB: {config.DB_HOST}:{config.DB_PORT}")
print(f"   Model: {config.DEEPSEEK_MODEL}")
print(f"   API Key: {'✓ Set' if config.DEEPSEEK_API_KEY else '✗ Missing'}")

# Test 2: Database Connection (via docker exec)
print("\n✅ Step 2: Testing database connection...")
print("   Using docker exec to connect...")

import subprocess
try:
    cmd = [
        'docker', 'exec', '-i', '-u', 'opentenbase',
        'otb-node1',
        '/data/opentenbase/install/opentenbase/5.21.8/bin/psql',
        '-X', '-p', '11003', '-d', 'postgres',
        '-t', '-c', 'SELECT version();'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        version = result.stdout.strip()[:80]
        print(f"   ✓ Connected: {version}")
    else:
        print(f"   ✗ Failed: {result.stderr}")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 3: Data Collection (simulated)
print("\n✅ Step 3: Testing data collection...")
print("   Simulating cluster data collection...")
sample_data = {
    'nodes': [
        {'node_name': 'otb-node1', 'node_type': 'coordinator', 'node_host': '172.28.50.11'},
        {'node_name': 'otb-node2', 'node_type': 'coordinator', 'node_host': '172.28.50.12'}
    ],
    'connections': {'total': 45, 'max_connections': 100},
}
print(f"   ✓ Sample data: {len(sample_data['nodes'])} nodes, {sample_data['connections']['total']} connections")

# Test 4: DeepSeek API
print("\n✅ Step 4: Testing DeepSeek API...")
if config.DEEPSEEK_API_KEY:
    try:
        llm = DeepSeekClient(config)
        print("   Testing simple query...")
        response = llm.answer_question(
            "什么是 OpenTenBase？用一句话回答。",
            context=None
        )
        print(f"   ✓ API Response: {response[:100]}...")
    except Exception as e:
        print(f"   ✗ API Error: {e}")
else:
    print("   ⚠ Skipping (no API key)")

print("\n" + "=" * 60)
print("✅ Quick test completed!")
print("=" * 60)
print("\n💡 Next steps:")
print("   1. Wait for Docker build to complete")
print("   2. Run: docker-compose up -d")
print("   3. Visit: http://localhost:8080")
