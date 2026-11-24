#!/usr/bin/env python3
"""
Comprehensive OpenTenBase Knowledge Base Builder

Imports:
1. Official documentation from GitHub
2. Common troubleshooting guides
3. Best practices
4. Performance tuning guides
5. Distributed database specific knowledge
"""
import sys
import os
from pathlib import Path
import requests
from typing import List, Dict
import time

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector
from backend.ai.embedding_client import EmbeddingClient
from backend.ai.knowledge_base_otb import KnowledgeBase

print("=" * 80)
print("OpenTenBase Comprehensive Knowledge Base Builder")
print("=" * 80)

# Initialize
config = Config()
db_connector = OpenTenBaseConnector(config)
embedding_client = EmbeddingClient(config)
knowledge_base = KnowledgeBase(db_connector, embedding_client)

print("\n✓ System initialized\n")

# ============================================================================
# PART 1: Official Documentation from GitHub
# ============================================================================

GITHUB_DOCS = [
    {
        'title': 'OpenTenBase 主仓库 README',
        'url': 'https://raw.githubusercontent.com/OpenTenBase/OpenTenBase/master/README.md',
        'category': 'official_doc',
        'version': 'latest'
    },
    {
        'title': 'OpenTenBase 中文 README',
        'url': 'https://raw.githubusercontent.com/OpenTenBase/OpenTenBase/master/README_CN.md',
        'category': 'official_doc',
        'version': 'latest'
    },
]

# ============================================================================
# PART 2: Installation & Deployment Guides
# ============================================================================

INSTALLATION_GUIDES = [
    {
        'title': 'OpenTenBase 快速安装指南',
        'content': """
# OpenTenBase 快速安装指南

## 系统要求

### 硬件要求
- CPU: 4 核以上
- 内存: 8GB 以上
- 磁盘: 100GB 以上 SSD

### 软件要求
- 操作系统: CentOS 7/8, Ubuntu 18.04+
- GCC: 4.8 以上
- CMake: 3.1 以上
- Git

## 安装步骤

### 1. 准备环境
```bash
# CentOS/RHEL
yum install -y gcc gcc-c++ make cmake git readline-devel zlib-devel

# Ubuntu/Debian
apt-get install -y gcc g++ make cmake git libreadline-dev zlib1g-dev
```

### 2. 下载源码
```bash
git clone https://github.com/OpenTenBase/OpenTenBase.git
cd OpenTenBase
```

### 3. 编译安装
```bash
# 配置
./configure --prefix=/opt/opentenbase --enable-user-switch

# 编译（使用多核加速）
make -j$(nproc)

# 安装
make install
```

### 4. 初始化集群

#### 单节点模式（测试用）
```bash
cd /opt/opentenbase
./bin/initdb -D data

# 修改配置
vi data/postgresql.conf
# 设置:
# listen_addresses = '*'
# port = 5432

# 启动
./bin/pg_ctl -D data start
```

#### 分布式集群模式

**准备节点规划**:
- GTM: 192.168.1.101
- Coordinator 1: 192.168.1.102
- Coordinator 2: 192.168.1.103
- Datanode 1: 192.168.1.104
- Datanode 2: 192.168.1.105

**初始化 GTM**:
```bash
# 在 GTM 节点
./bin/initgtm -Z gtm -D /data/gtm

# 启动
./bin/gtm -D /data/gtm -l /data/gtm/gtm.log &
```

**初始化 Coordinator**:
```bash
# 在 CN 节点
./bin/initdb -D /data/coord --nodename=coord1

# 配置
vi /data/coord/postgresql.conf
# 设置:
# gtm_host = '192.168.1.101'
# gtm_port = 6666

# 启动
./bin/pg_ctl -D /data/coord start
```

**初始化 Datanode**:
```bash
# 在 DN 节点
./bin/initdb -D /data/datanode --nodename=dn1

# 配置
vi /data/datanode/postgresql.conf
# 设置:
# gtm_host = '192.168.1.101'
# gtm_port = 6666

# 启动
./bin/pg_ctl -D /data/datanode start
```

### 5. 验证安装
```bash
# 连接数据库
./bin/psql -h 192.168.1.102 -p 5432 -U postgres

# 检查节点
SELECT * FROM pgxc_node;

# 测试分布式
CREATE TABLE test (id int) DISTRIBUTE BY SHARD(id);
INSERT INTO test SELECT generate_series(1, 1000);
SELECT count(*) FROM test;
```

## 常见问题

### 编译失败
- 检查 GCC 版本: `gcc --version`
- 安装缺失依赖: `yum install -y readline-devel zlib-devel`

### GTM 启动失败
- 检查端口占用: `netstat -tuln | grep 6666`
- 查看日志: `tail -f /data/gtm/gtm.log`

### 节点连接失败
- 检查防火墙: `systemctl stop firewalld`
- 检查 pg_hba.conf: 添加 `host all all 0.0.0.0/0 trust`

## 下一步
- 配置主从复制
- 性能调优
- 监控部署
""",
        'category': 'installation',
        'version': '1.0',
        'source_url': 'https://github.com/OpenTenBase/OpenTenBase'
    },
]

# ============================================================================
# PART 3: Performance Tuning Guides
# ============================================================================

PERFORMANCE_GUIDES = [
    {
        'title': 'OpenTenBase 性能优化指南',
        'content': """
# OpenTenBase 性能优化指南

## 1. 硬件优化

### CPU
- 推荐 Intel Xeon 或 AMD EPYC
- 核心数越多越好（分布式并行）
- 开启超线程

### 内存
- 至少 64GB
- 推荐 128GB+
- ECC 内存（数据安全）

### 磁盘
- **强烈推荐 NVMe SSD**
- RAID 10（性能 + 冗余）
- 单独挂载数据目录和 WAL 目录

### 网络
- 万兆网卡（10GbE）
- 低延迟交换机
- 节点间直连（可选）

## 2. 配置参数优化

### 内存相关
```sql
-- 共享缓冲区（总内存的 25%）
ALTER SYSTEM SET shared_buffers = '32GB';

-- 工作内存（复杂查询）
ALTER SYSTEM SET work_mem = '256MB';

-- 维护内存（VACUUM, CREATE INDEX）
ALTER SYSTEM SET maintenance_work_mem = '2GB';

-- 有效缓存大小（用于查询优化器）
ALTER SYSTEM SET effective_cache_size = '96GB';
```

### 连接相关
```sql
-- 最大连接数
ALTER SYSTEM SET max_connections = 500;

-- 连接超时
ALTER SYSTEM SET statement_timeout = '300s';
ALTER SYSTEM SET idle_in_transaction_session_timeout = '600s';
```

### WAL 相关
```sql
-- WAL 缓冲区
ALTER SYSTEM SET wal_buffers = '16MB';

-- 检查点
ALTER SYSTEM SET checkpoint_timeout = '15min';
ALTER SYSTEM SET max_wal_size = '4GB';
ALTER SYSTEM SET min_wal_size = '1GB';

-- WAL 写入模式
ALTER SYSTEM SET synchronous_commit = 'off';  -- 注意：降低持久性
```

### 查询优化器
```sql
-- 开启并行查询
ALTER SYSTEM SET max_parallel_workers_per_gather = 4;
ALTER SYSTEM SET max_parallel_workers = 16;

-- JIT 编译（PG 11+）
ALTER SYSTEM SET jit = on;

-- 统计信息
ALTER SYSTEM SET default_statistics_target = 100;
```

### 分布式特定
```sql
-- GTM 相关
ALTER SYSTEM SET gtm_connect_timeout = '10s';

-- 数据节点池化
ALTER SYSTEM SET max_pool_size = 100;
ALTER SYSTEM SET pool_maintenance_timeout = '60s';
```

### 应用后重载
```sql
SELECT pg_reload_conf();
```

## 3. 分片策略优化

### 选择合适的分片键
```sql
-- ❌ 不好的分片键（热点）
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP
) DISTRIBUTE BY SHARD(id);  -- SERIAL 递增会导致热点

-- ✅ 好的分片键（均匀分布）
CREATE TABLE orders (
    id UUID PRIMARY KEY,
    user_id INT,
    created_at TIMESTAMP
) DISTRIBUTE BY SHARD(user_id);  -- 用户 ID 分布均匀
```

### 复制表 vs 分片表
```sql
-- 小表用复制表（避免跨节点 JOIN）
CREATE TABLE country (
    id INT PRIMARY KEY,
    name TEXT
) DISTRIBUTE BY REPLICATION;

-- 大表用分片表
CREATE TABLE transactions (
    id BIGINT PRIMARY KEY,
    amount DECIMAL
) DISTRIBUTE BY SHARD(id);
```

## 4. 索引优化

### 合理创建索引
```sql
-- 查询条件字段
CREATE INDEX idx_orders_user ON orders(user_id);

-- 复合索引（查询顺序很重要）
CREATE INDEX idx_orders_user_time ON orders(user_id, created_at DESC);

-- 部分索引（节省空间）
CREATE INDEX idx_orders_pending ON orders(user_id) WHERE status = 'pending';
```

### 避免过多索引
- 每个索引会增加写入成本
- 定期检查未使用的索引

```sql
-- 查找未使用的索引
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND indexname NOT LIKE '%_pkey';
```

## 5. 查询优化

### 避免全表扫描
```sql
-- ❌ 没有 WHERE 条件
SELECT * FROM large_table;

-- ✅ 使用索引
SELECT * FROM large_table WHERE user_id = 123;
```

### 使用 EXPLAIN ANALYZE
```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE user_id = 123;
```

### 批量操作
```sql
-- ❌ 逐条插入
INSERT INTO orders VALUES (1, ...);
INSERT INTO orders VALUES (2, ...);

-- ✅ 批量插入
INSERT INTO orders VALUES
(1, ...),
(2, ...),
(3, ...);

-- 更好：使用 COPY
COPY orders FROM '/tmp/data.csv' CSV;
```

## 6. 维护操作

### 定期 VACUUM
```sql
-- 手动 VACUUM
VACUUM ANALYZE orders;

-- 配置自动 VACUUM
ALTER SYSTEM SET autovacuum = on;
ALTER SYSTEM SET autovacuum_max_workers = 4;
ALTER SYSTEM SET autovacuum_naptime = '1min';
```

### 定期 ANALYZE
```sql
-- 更新统计信息
ANALYZE orders;

-- 自动 ANALYZE
ALTER SYSTEM SET autovacuum_analyze_threshold = 50;
```

### 监控膨胀
```sql
-- 检查表膨胀
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

## 7. 监控指标

### 关键指标
- QPS（每秒查询数）
- 平均响应时间
- 连接数使用率
- 缓存命中率
- 复制延迟
- 磁盘 IO 利用率

### 监控查询
```sql
-- 缓存命中率
SELECT
    sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) as cache_hit_ratio
FROM pg_statio_user_tables;

-- 慢查询
SELECT
    query,
    calls,
    total_time,
    mean_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;
```

## 8. 常见性能问题

### 问题1: 查询慢
**排查**: EXPLAIN ANALYZE
**解决**: 添加索引、优化 SQL、更新统计信息

### 问题2: 写入慢
**排查**: 检查索引数量、磁盘 IO
**解决**: 减少索引、使用批量插入、升级磁盘

### 问题3: 连接数耗尽
**排查**: pg_stat_activity
**解决**: 使用连接池（PgBouncer）、增加 max_connections

### 问题4: 内存不足
**排查**: 查看 work_mem 使用
**解决**: 调整 work_mem、增加物理内存

## 9. 最佳实践

1. **定期备份**：pg_dump + WAL 归档
2. **监控告警**：Prometheus + Grafana
3. **压力测试**：pgbench
4. **容量规划**：预留 30% 增长空间
5. **文档化**：记录所有配置变更

## 参考资源
- PostgreSQL 官方性能调优: https://wiki.postgresql.org/wiki/Performance_Optimization
- OpenTenBase GitHub: https://github.com/OpenTenBase/OpenTenBase
""",
        'category': 'performance',
        'version': '1.0',
        'source_url': 'https://github.com/OpenTenBase/OpenTenBase/wiki'
    },
]

# ============================================================================
# PART 4: Distributed Database Specific
# ============================================================================

DISTRIBUTED_GUIDES = [
    {
        'title': 'OpenTenBase 分布式特性详解',
        'content': """
# OpenTenBase 分布式数据库特性

## 架构组件

### 1. GTM (Global Transaction Manager)
**作用**: 全局事务管理、全局序列号、全局快照

**配置**:
```sql
-- GTM 参数
gtm_host = '192.168.1.101'
gtm_port = 6666
gtm_connect_timeout = '10s'
```

**监控**:
```bash
# 检查 GTM 状态
gtm_ctl status -D /data/gtm
```

### 2. Coordinator (CN)
**作用**: SQL 解析、查询优化、结果聚合

**特点**:
- 无状态（可横向扩展）
- 客户端连接入口
- 负责分布式查询计划

**最佳实践**:
- 部署多个 CN 做负载均衡
- CN 节点配置相同
- 使用 Pgpool-II 做连接池

### 3. Datanode (DN)
**作用**: 实际存储数据

**分片策略**:
```sql
-- SHARD 分片（大表）
CREATE TABLE orders (...) DISTRIBUTE BY SHARD(user_id);

-- REPLICATION 复制（小表）
CREATE TABLE config (...) DISTRIBUTE BY REPLICATION;

-- MODULO 取模（旧版）
CREATE TABLE logs (...) DISTRIBUTE BY MODULO(log_id);
```

## 分布式查询

### 本地查询 vs 跨节点查询
```sql
-- ✅ 本地查询（单分片）
SELECT * FROM orders WHERE user_id = 123;
-- 只访问一个 DN

-- ⚠️ 跨节点查询（全局）
SELECT * FROM orders WHERE amount > 1000;
-- 需要访问所有 DN 并聚合
```

### 分布式 JOIN
```sql
-- ✅ 高效 JOIN（分片键相同）
SELECT o.*, u.name
FROM orders o
JOIN users u ON o.user_id = u.user_id;
-- 本地 JOIN，无数据移动

-- ⚠️ 低效 JOIN（分片键不同）
SELECT o.*, p.name
FROM orders o
JOIN products p ON o.product_id = p.id;
-- 需要重分布数据（redistribution）
```

### 查看查询计划
```sql
EXPLAIN (VERBOSE, COSTS)
SELECT * FROM orders WHERE user_id = 123;

-- 关注：
-- - Remote Query: 下推到 DN 的查询
-- - Data Node Scan: DN 本地扫描
-- - Materialize: 数据物化（可能很慢）
```

## 分布式事务

### ACID 保证
OpenTenBase 支持完整的分布式 ACID:
- **原子性**: GTM 协调两阶段提交（2PC）
- **一致性**: 全局快照隔离
- **隔离性**: 支持 READ COMMITTED, REPEATABLE READ
- **持久性**: WAL 日志

### 分布式死锁
```sql
-- 检测死锁
SELECT * FROM pg_locks WHERE NOT granted;

-- 解决死锁
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'active' AND wait_event_type = 'Lock';
```

## 数据分布管理

### 查看分片信息
```sql
-- 查看表分布策略
SELECT * FROM pgxc_class WHERE pcrelid = 'orders'::regclass;

-- 查看数据分布
SELECT
    n.node_name,
    count(*) as row_count
FROM orders o
JOIN pgxc_node n ON n.node_id = ANY(SELECT nodeids FROM pgxc_class WHERE pcrelid = 'orders'::regclass)
GROUP BY n.node_name;
```

### 数据倾斜检测
```bash
# 在每个 DN 上执行
SELECT 'dn1' as node, count(*) FROM orders;
SELECT 'dn2' as node, count(*) FROM orders;

# 比较行数差异
# 如果差异 >20%，说明数据倾斜
```

### 重分布（Redistribute）
```sql
-- 创建新表（使用更好的分片键）
CREATE TABLE orders_new (...)
DISTRIBUTE BY SHARD(better_key);

-- 迁移数据
INSERT INTO orders_new SELECT * FROM orders;

-- 切换表名
ALTER TABLE orders RENAME TO orders_old;
ALTER TABLE orders_new RENAME TO orders;
```

## 扩容与缩容

### 添加 Datanode
```bash
# 1. 初始化新 DN
initdb -D /data/dn3 --nodename=dn3

# 2. 启动 DN
pg_ctl -D /data/dn3 start

# 3. 在 CN 上注册
ALTER NODE dn3 ADD DATANODE WITH (HOST='192.168.1.106', PORT=5432);

# 4. 重分布数据
-- 需要逐表迁移数据
```

### 删除 Datanode
```bash
# 1. 迁移数据到其他 DN

# 2. 在 CN 上删除
ALTER NODE dn3 DROP DATANODE;

# 3. 停止 DN
pg_ctl -D /data/dn3 stop
```

## 高可用

### 主从复制
```bash
# 从库配置
recovery.conf:
standby_mode = 'on'
primary_conninfo = 'host=master_host port=5432'
```

### 自动故障切换
- 使用 Pgpool-II watchdog
- 或者 Patroni + etcd

### 备份策略
```bash
# 全量备份
pg_basebackup -h cn1 -U postgres -D /backup/full

# 增量备份（WAL 归档）
archive_mode = on
archive_command = 'cp %p /archive/%f'
```

## 监控指标

### 分布式特定指标
- GTM 事务分配速率
- DN 间数据移动量
- 跨节点查询比例
- 分片数据均衡度

### 监控查询
```sql
-- DN 数据量
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables
WHERE schemaname = 'public';

-- 跨节点查询统计
SELECT
    query,
    calls,
    mean_time
FROM pg_stat_statements
WHERE query LIKE '%Remote%'
ORDER BY calls DESC;
```

## 最佳实践

1. **分片键选择**:
   - 选择查询常用的列
   - 保证数据均匀分布
   - 避免热点

2. **小表复制**:
   - 字典表用 REPLICATION
   - 避免跨节点 JOIN

3. **批量操作**:
   - 使用 COPY 而不是 INSERT
   - 大事务分批提交

4. **监控预警**:
   - GTM 可用性
   - DN 数据倾斜
   - 跨节点查询占比

5. **容量规划**:
   - 预留扩展空间
   - DN 数量为 2 的幂次（方便取模）

## 故障处理

### GTM 故障
**影响**: 整个集群不可用
**恢复**:
1. 重启 GTM
2. 或者切换到 GTM Standby

### CN 故障
**影响**: 部分客户端连接断开
**恢复**: 客户端重连到其他 CN

### DN 故障
**影响**: 部分数据不可访问
**恢复**:
1. 如果有从库，提升从库为主库
2. 或者从备份恢复

## 参考资料
- OpenTenBase 架构文档
- PostgreSQL-XL 文档
- Distributed PostgreSQL 最佳实践
""",
        'category': 'distributed',
        'version': '1.0',
        'source_url': 'https://github.com/OpenTenBase/OpenTenBase'
    },
]

# ============================================================================
# PART 5: More Troubleshooting Guides
# ============================================================================

MORE_TROUBLESHOOTING = [
    {
        'title': '慢查询诊断与优化',
        'content': """
# OpenTenBase 慢查询诊断与优化

## 识别慢查询

### 方法1: pg_stat_statements
```sql
-- 开启扩展
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 查看最慢的查询
SELECT
    query,
    calls,
    total_time,
    mean_time,
    max_time,
    stddev_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 20;
```

### 方法2: 日志
```sql
-- 配置慢查询日志
ALTER SYSTEM SET log_min_duration_statement = '1000';  -- 1秒
ALTER SYSTEM SET log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h ';

-- 重载配置
SELECT pg_reload_conf();

-- 查看日志
tail -f /data/postgresql/log/postgresql-*.log | grep "duration:"
```

## 诊断步骤

### 1. 获取执行计划
```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, TIMING)
SELECT * FROM orders WHERE user_id = 123;
```

**关注指标**:
- **Seq Scan**: 全表扫描（通常很慢）
- **Buffers**: 缓冲区读取（shared hit vs read）
- **Planning Time**: 规划时间
- **Execution Time**: 执行时间

### 2. 检查索引使用
```sql
-- 查看表的索引
\\d orders

-- 查看索引使用情况
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND tablename = 'orders';
```

### 3. 检查统计信息
```sql
-- 查看表统计信息更新时间
SELECT
    schemaname,
    tablename,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    n_live_tup,
    n_dead_tup
FROM pg_stat_user_tables
WHERE tablename = 'orders';

-- 如果统计信息过期，手动更新
ANALYZE orders;
```

## 常见问题与解决

### 问题1: 全表扫描
**症状**: Seq Scan on large_table

**原因**:
- 缺少索引
- 索引失效
- 查询返回大量数据

**解决**:
```sql
-- 创建索引
CREATE INDEX idx_orders_user ON orders(user_id);

-- 如果索引存在但未使用，检查统计信息
ANALYZE orders;

-- 或者强制使用索引
SET enable_seqscan = off;  -- 仅用于测试
```

### 问题2: 索引扫描仍然慢
**症状**: Index Scan 耗时长

**原因**:
- 索引膨胀
- 返回数据量大
- 随机 IO

**解决**:
```sql
-- 重建索引
REINDEX INDEX idx_orders_user;

-- 或者创建覆盖索引（包含查询所需的所有列）
CREATE INDEX idx_orders_user_covering ON orders(user_id) INCLUDE (amount, created_at);
```

### 问题3: JOIN 慢
**症状**: Hash Join / Nested Loop 耗时长

**原因**:
- 表统计信息过期
- JOIN 条件没有索引
- 数据分布不均

**解决**:
```sql
-- 更新统计信息
ANALYZE orders;
ANALYZE users;

-- 在 JOIN 列上创建索引
CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_users_id ON users(id);

-- 查看 JOIN 方式
EXPLAIN SELECT * FROM orders o JOIN users u ON o.user_id = u.id;
```

### 问题4: 排序慢
**症状**: Sort 操作耗时长

**原因**:
- work_mem 不足，使用磁盘排序
- 排序数据量大

**解决**:
```sql
-- 增加 work_mem（仅当前会话）
SET work_mem = '256MB';

-- 或者创建索引避免排序
CREATE INDEX idx_orders_created ON orders(created_at DESC);
```

### 问题5: 分布式查询慢
**症状**: Remote Query 耗时长

**原因**:
- 跨节点数据传输
- 没有下推到 DN

**解决**:
```sql
-- 优化分片键
-- 让查询只访问单个 DN
SELECT * FROM orders WHERE user_id = 123;  -- 分片键

-- 避免跨节点聚合
-- 使用分片键进行 GROUP BY
SELECT user_id, count(*) FROM orders GROUP BY user_id;
```

## 优化技巧

### 1. 使用合适的索引类型
```sql
-- B-Tree (默认，适合等值和范围查询)
CREATE INDEX idx_orders_amount ON orders(amount);

-- Hash (仅等值查询)
CREATE INDEX idx_orders_status ON orders USING HASH(status);

-- GIN (全文搜索、数组)
CREATE INDEX idx_orders_tags ON orders USING GIN(tags);
```

### 2. 部分索引
```sql
-- 只索引活跃订单
CREATE INDEX idx_orders_active ON orders(user_id) WHERE status = 'active';
```

### 3. 表达式索引
```sql
-- 索引计算列
CREATE INDEX idx_orders_year ON orders(EXTRACT(YEAR FROM created_at));
```

### 4. 避免 SELECT *
```sql
-- ❌ 返回所有列
SELECT * FROM orders WHERE user_id = 123;

-- ✅ 只返回需要的列
SELECT id, amount, created_at FROM orders WHERE user_id = 123;
```

### 5. 使用 LIMIT
```sql
-- ❌ 返回所有行
SELECT * FROM orders ORDER BY created_at DESC;

-- ✅ 限制返回行数
SELECT * FROM orders ORDER BY created_at DESC LIMIT 100;
```

### 6. 避免隐式类型转换
```sql
-- ❌ 隐式转换导致索引失效
SELECT * FROM orders WHERE user_id = '123';  -- user_id 是 INT

-- ✅ 显式类型
SELECT * FROM orders WHERE user_id = 123;
```

## 监控与预防

### 定期检查
```sql
-- 每周检查慢查询
SELECT
    query,
    calls,
    mean_time,
    total_time
FROM pg_stat_statements
WHERE mean_time > 1000  -- 超过 1 秒
ORDER BY mean_time DESC;

-- 重置统计
SELECT pg_stat_statements_reset();
```

### 自动化
```bash
# crontab 定期分析
0 2 * * * psql -c "ANALYZE" mydatabase
```

### 告警阈值
- 平均查询时间 > 1s: WARNING
- 平均查询时间 > 5s: CRITICAL
- 慢查询占比 > 10%: WARNING

## 工具推荐
- **pg_stat_statements**: 查询统计
- **auto_explain**: 自动记录慢查询执行计划
- **pg_hint_plan**: 强制查询计划
- **pgBadger**: 日志分析工具

""",
        'category': 'troubleshooting',
        'version': '1.0',
        'source_url': 'https://github.com/OpenTenBase/OpenTenBase/wiki'
    },
]

# ============================================================================
# Import Functions
# ============================================================================

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
                time.sleep(0.5)  # Rate limiting
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
            time.sleep(0.3)  # Rate limiting for embedding API
            return True
        else:
            print(f"   ✗ Import failed")
            return False

    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

# ============================================================================
# Main Import Process
# ============================================================================

success_count = 0
fail_count = 0

print("=" * 80)
print("Phase 1: Official GitHub Documentation")
print("=" * 80)

for doc in GITHUB_DOCS:
    if import_from_url(doc):
        success_count += 1
    else:
        fail_count += 1

print("\n" + "=" * 80)
print("Phase 2: Installation & Deployment Guides")
print("=" * 80)

for doc in INSTALLATION_GUIDES:
    if import_direct(doc):
        success_count += 1
    else:
        fail_count += 1

print("\n" + "=" * 80)
print("Phase 3: Performance Tuning Guides")
print("=" * 80)

for doc in PERFORMANCE_GUIDES:
    if import_direct(doc):
        success_count += 1
    else:
        fail_count += 1

print("\n" + "=" * 80)
print("Phase 4: Distributed Database Guides")
print("=" * 80)

for doc in DISTRIBUTED_GUIDES:
    if import_direct(doc):
        success_count += 1
    else:
        fail_count += 1

print("\n" + "=" * 80)
print("Phase 5: Troubleshooting Guides")
print("=" * 80)

for doc in MORE_TROUBLESHOOTING:
    if import_direct(doc):
        success_count += 1
    else:
        fail_count += 1

# ============================================================================
# Summary & Statistics
# ============================================================================

print("\n" + "=" * 80)
print("Import Summary")
print("=" * 80)
print(f"✓ Success: {success_count}")
print(f"✗ Failed: {fail_count}")
print(f"Total: {success_count + fail_count}")

# Query statistics
stats = knowledge_base.get_statistics()
print("\n" + "=" * 80)
print("Knowledge Base Statistics")
print("=" * 80)
print(f"Documents: {stats.get('total_documents', 0)}")
print(f"Chunks: {stats.get('total_chunks', 0)}")
print(f"Categories: {stats.get('total_categories', 0)}")

if stats.get('categories'):
    print("\nBy Category:")
    for cat in stats['categories']:
        print(f"  - {cat['category']}: {cat['count']} docs")

# ============================================================================
# Search Tests
# ============================================================================

print("\n" + "=" * 80)
print("Search Tests")
print("=" * 80)

test_queries = [
    "如何安装 OpenTenBase",
    "查询性能优化",
    "分布式事务如何工作",
    "慢查询怎么诊断",
    "主从复制延迟",
]

for query in test_queries:
    print(f"\n🔍 Query: {query}")
    results = knowledge_base.search(query, top_k=3)
    if results:
        for i, r in enumerate(results, 1):
            print(f"    {i}. [{r['category']}] {r['title']}")
            print(f"       Similarity: {r['similarity']:.3f}")
    else:
        print("    No results")

print("\n" + "=" * 80)
print("✅ Knowledge Base Build Completed!")
print("=" * 80)
print("\nNext steps:")
print("1. Verify search results quality")
print("2. Add more specific troubleshooting cases")
print("3. Integrate with AI diagnostic engine")
