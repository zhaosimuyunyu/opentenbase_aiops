#!/usr/bin/env python3
"""
Import OpenTenBase official documentation into knowledge base

Sources:
- GitHub Wiki
- README files
- Documentation folder
"""
import sys
import os
from pathlib import Path
import requests
from typing import List, Dict

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector
from backend.ai.embedding_client import EmbeddingClient
from backend.ai.knowledge_base import KnowledgeBase

print("=" * 70)
print("OpenTenBase Knowledge Base Import")
print("=" * 70)

# Initialize
config = Config()
db_connector = OpenTenBaseConnector(config)
embedding_client = EmbeddingClient(config)
knowledge_base = KnowledgeBase(db_connector, embedding_client)

print("\n✓ System initialized")

# Define documentation sources
OFFICIAL_DOCS = [
    {
        'title': 'OpenTenBase README',
        'url': 'https://raw.githubusercontent.com/OpenTenBase/OpenTenBase/master/README.md',
        'category': 'official_doc',
        'version': '1.0'
    },
    {
        'title': 'OpenTenBase README (中文)',
        'url': 'https://raw.githubusercontent.com/OpenTenBase/OpenTenBase/master/README_CN.md',
        'category': 'official_doc',
        'version': '1.0'
    },
]

# Troubleshooting guides
TROUBLESHOOTING_DOCS = [
    {
        'title': '主从复制延迟问题排查',
        'content': """
# OpenTenBase 主从复制延迟问题排查

## 问题描述
主从复制延迟（Replication Lag）是指主库执行的事务，从库需要一段时间才能同步。

## 常见原因

### 1. 从库磁盘 IO 饱和
- 症状：从库 `iowait` 高（>50%）
- 原因：大量写入导致磁盘 IO 瓶颈
- 排查命令：
  ```sql
  -- 查看复制延迟
  SELECT * FROM pg_stat_replication;

  -- 查看 IO 等待
  SELECT wait_event_type, wait_event, count(*)
  FROM pg_stat_activity
  GROUP BY wait_event_type, wait_event;
  ```

### 2. 网络带宽不足
- 症状：复制延迟波动大
- 原因：网络延迟或带宽限制
- 排查：检查网络监控

### 3. 大事务导致延迟
- 症状：突发性延迟峰值
- 原因：单个大事务阻塞复制流
- 排查：
  ```sql
  -- 查看长事务
  SELECT pid, query_start, NOW() - query_start as duration, query
  FROM pg_stat_activity
  WHERE state != 'idle'
  ORDER BY duration DESC;
  ```

### 4. 配置问题
- `max_wal_senders` 过小
- `wal_sender_timeout` 配置不当
- 从库资源配置不足

## 解决方案

### 短期措施
1. **清理表膨胀**：
   ```sql
   VACUUM ANALYZE table_name;
   ```

2. **临时降低从库负载**：
   - 停止从库的只读查询
   - 暂时关闭备份任务

3. **增加 max_wal_senders**：
   ```sql
   ALTER SYSTEM SET max_wal_senders = 10;
   SELECT pg_reload_conf();
   ```

### 长期优化
1. **升级硬件**：
   - 使用 SSD
   - 增加从库内存
   - 提升网络带宽

2. **优化应用**：
   - 减小事务大小
   - 批量操作分批提交

3. **调整参数**：
   ```sql
   -- 增加 checkpoint 间隔
   ALTER SYSTEM SET checkpoint_timeout = '15min';
   ALTER SYSTEM SET max_wal_size = '4GB';
   ```

## 验证方法
```sql
-- 持续监控复制延迟
SELECT
    client_addr,
    state,
    sync_state,
    replay_lag,
    write_lag,
    flush_lag
FROM pg_stat_replication;
```

## 参考文档
- PostgreSQL Replication: https://www.postgresql.org/docs/10/warm-standby.html
- OpenTenBase 复制配置：官方文档
""",
        'category': 'troubleshooting',
        'version': '1.0',
        'source_url': 'https://github.com/OpenTenBase/OpenTenBase/wiki'
    },
    {
        'title': '连接数接近上限问题处理',
        'content': """
# OpenTenBase 连接数接近上限问题

## 问题症状
- 应用报错：`FATAL: remaining connection slots are reserved`
- 新连接无法建立
- 查询响应变慢

## 原因分析

### 1. 连接泄漏
应用未正确关闭数据库连接

### 2. 连接池配置不当
连接池大小超过数据库 `max_connections`

### 3. 慢查询占用连接
长时间运行的查询占用连接资源

## 排查步骤

### 1. 查看当前连接数
```sql
SELECT
    datname,
    count(*) as connections
FROM pg_stat_activity
GROUP BY datname
ORDER BY connections DESC;
```

### 2. 查看连接状态
```sql
SELECT
    state,
    count(*)
FROM pg_stat_activity
GROUP BY state;
```

### 3. 查找空闲连接
```sql
SELECT
    pid,
    datname,
    usename,
    state,
    NOW() - state_change as idle_time
FROM pg_stat_activity
WHERE state = 'idle'
ORDER BY idle_time DESC;
```

## 解决方案

### 临时措施
1. **杀掉空闲连接**：
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle'
     AND NOW() - state_change > interval '1 hour';
   ```

2. **增加 max_connections**（需重启）：
   ```sql
   ALTER SYSTEM SET max_connections = 200;
   -- 需要重启数据库
   ```

### 长期优化
1. **使用连接池**：
   - PgBouncer
   - Pgpool-II

2. **优化应用**：
   - 确保连接及时关闭
   - 使用连接池
   - 设置合理的超时

3. **监控告警**：
   - 连接数达到 80% 告警
   - 定期检查空闲连接

## 预防措施
```sql
-- 设置空闲连接超时
ALTER SYSTEM SET idle_in_transaction_session_timeout = '30min';

-- 设置语句超时
ALTER SYSTEM SET statement_timeout = '5min';
```

## 验证
```sql
SHOW max_connections;

SELECT count(*) as current_connections,
       current_setting('max_connections')::int as max_connections,
       (count(*)::float / current_setting('max_connections')::int * 100)::numeric(5,2) as usage_percent
FROM pg_stat_activity;
```
""",
        'category': 'troubleshooting',
        'version': '1.0',
        'source_url': 'https://github.com/OpenTenBase/OpenTenBase/wiki'
    },
]

# Import function
def import_from_url(doc: Dict) -> bool:
    """Import document from URL"""
    try:
        print(f"\n📄 Fetching: {doc['title']}")
        response = requests.get(doc['url'], timeout=30)

        if response.status_code == 200:
            content = response.text
            print(f"   ✓ Downloaded ({len(content)} bytes)")

            entity_id = knowledge_base.add_document(
                title=doc['title'],
                content=content,
                category=doc['category'],
                source_url=doc['url'],
                version=doc['version']
            )

            if entity_id:
                print(f"   ✓ Imported: {entity_id}")
                return True
            else:
                print(f"   ✗ Import failed")
                return False
        else:
            print(f"   ✗ HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

def import_direct(doc: Dict) -> bool:
    """Import document with direct content"""
    try:
        print(f"\n📄 Importing: {doc['title']}")

        entity_id = knowledge_base.add_document(
            title=doc['title'],
            content=doc['content'],
            category=doc['category'],
            source_url=doc.get('source_url'),
            version=doc['version']
        )

        if entity_id:
            print(f"   ✓ Imported: {entity_id}")
            return True
        else:
            print(f"   ✗ Import failed")
            return False

    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

# Main import process
print("\n" + "=" * 70)
print("Phase 1: Import Official Documentation")
print("=" * 70)

success_count = 0
fail_count = 0

for doc in OFFICIAL_DOCS:
    if import_from_url(doc):
        success_count += 1
    else:
        fail_count += 1

print("\n" + "=" * 70)
print("Phase 2: Import Troubleshooting Guides")
print("=" * 70)

for doc in TROUBLESHOOTING_DOCS:
    if import_direct(doc):
        success_count += 1
    else:
        fail_count += 1

# Statistics
print("\n" + "=" * 70)
print("Import Summary")
print("=" * 70)
print(f"✓ Success: {success_count}")
print(f"✗ Failed: {fail_count}")
print(f"Total: {success_count + fail_count}")

# Query statistics
stats = knowledge_base.get_statistics()
print("\n" + "=" * 70)
print("Knowledge Base Statistics")
print("=" * 70)
print(f"Documents: {stats.get('total_documents', 0)}")
print(f"Chunks: {stats.get('total_chunks', 0)}")
print(f"Categories: {stats.get('total_categories', 0)}")

if stats.get('categories'):
    print("\nBy Category:")
    for cat in stats['categories']:
        print(f"  - {cat['category']}: {cat['count']} docs")

# Test search
print("\n" + "=" * 70)
print("Search Test")
print("=" * 70)

test_queries = [
    "主从复制延迟怎么解决",
    "连接数太多怎么办",
    "如何优化查询性能"
]

for query in test_queries:
    print(f"\nQuery: {query}")
    results = knowledge_base.search(query, top_k=2)
    if results:
        print(f"  Found {len(results)} results:")
        for i, r in enumerate(results, 1):
            print(f"    {i}. {r['title']} (similarity: {r['similarity']:.3f})")
    else:
        print("  No results")

print("\n" + "=" * 70)
print("✓ Import completed!")
print("=" * 70)
