"""Simple connection test using docker exec"""
import subprocess
import json
import sys

# Fix Windows encoding issue
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 60)
print("OpenTenBase AIOps - Connection Test")
print("=" * 60)

# Test 1: Check OpenTenBase containers
print("\n[1] Checking OpenTenBase containers...")
try:
    result = subprocess.run(
        ['docker', 'ps', '--filter', 'name=otb', '--format', '{{.Names}}\t{{.Status}}'],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0 and result.stdout.strip():
        print("✅ OpenTenBase containers found:")
        for line in result.stdout.strip().split('\n'):
            print(f"   {line}")
    else:
        print("⚠️  No OpenTenBase containers running")
        print("   Please start with: docker start otb-node1 otb-node2")
except Exception as e:
    print(f"❌ Error: {e}")

# Test 2: Database connection
print("\n[2] Testing database connection...")
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
        version = result.stdout.strip()[:100]
        print(f"[OK] Database connected")
        print(f"   Version: {version}...")
    else:
        print(f"[FAIL] Connection failed")
        print(f"   Error: {result.stderr}")
except Exception as e:
    print(f"[ERROR] {e}")

# Test 3: Cluster query
print("\n[3] Testing cluster query...")
try:
    sql = "SELECT node_name, node_type, node_host FROM pgxc_node LIMIT 5;"
    cmd = [
        'docker', 'exec', '-i', '-u', 'opentenbase',
        'otb-node1',
        '/data/opentenbase/install/opentenbase/5.21.8/bin/psql',
        '-X', '-p', '11003', '-d', 'postgres',
        '-t', '-c', sql
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip():
        print("[OK] Cluster nodes:")
        for line in result.stdout.strip().split('\n'):
            print(f"   {line}")
    else:
        print("[WARN] No node data returned")
except Exception as e:
    print(f"[ERROR] {e}")

# Test 4: DeepSeek API
print("\n[4] Testing DeepSeek API...")
try:
    import requests
    from backend.utils.config import Config

    api_key = Config.DEEPSEEK_API_KEY
    api_url = f"{Config.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"

    if not api_key:
        print("[WARN] DEEPSEEK_API_KEY is not configured, skipping")
    else:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": Config.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "user", "content": "用一句话介绍 OpenTenBase 数据库"}
                ],
                "max_tokens": 100
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            answer = data['choices'][0]['message']['content']
            print("[OK] DeepSeek API working")
            print(f"   Response: {answer}")
        else:
            print(f"[FAIL] API Error: {response.status_code}")
            print(f"   {response.text[:200]}")
except ImportError:
    print("[WARN] requests module not installed, skipping")
except Exception as e:
    print(f"[ERROR] {e}")

# Test 5: Check Docker network
print("\n[5] Checking Docker network...")
try:
    result = subprocess.run(
        ['docker', 'network', 'inspect', 'otb-lab-net'],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        containers = data[0].get('Containers', {})
        print(f"[OK] Network 'otb-lab-net' exists")
        print(f"   Containers: {len(containers)}")
        for container_id, info in list(containers.items())[:3]:
            print(f"   - {info.get('Name', 'unknown')}: {info.get('IPv4Address', 'N/A')}")
    else:
        print("[WARN] Network 'otb-lab-net' not found")
except Exception as e:
    print(f"[ERROR] {e}")

print("\n" + "=" * 60)
print("Test Summary:")
print("  If all tests pass, you can proceed with:")
print("  1. Wait for docker build (running in background)")
print("  2. docker-compose up -d")
print("  3. Open http://localhost:8080")
print("=" * 60)
