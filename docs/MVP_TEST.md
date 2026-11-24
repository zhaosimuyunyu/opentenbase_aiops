# AIOps MVP 闭环测试报告

## 测试脚本

`scripts/test_mvp_loop.py` - 最小可验证闭环

## 验证目标

完成一个完整的 AIOps 闭环：

```
官方文档 
→ 知识库导入 
→ 向量化存储 
→ 语义检索 
→ AI 诊断建议 
→ 审批请求 
→ 人工审批 
→ 执行操作 
→ 审计记录
```

## 运行方法

```bash
cd E:\opentenbase\kaiyuan_contribute\opentenbase-aiops

# 确保 OpenTenBase 运行中
docker ps | grep otb

# 运行 MVP 测试
python scripts/test_mvp_loop.py
```

## 验收标准

### ✅ 必须通过

1. **知识库表创建成功**
   - `knowledge_entities` 表存在
   - `knowledge_embeddings` 表存在
   - `knowledge_retrieval_log` 表存在

2. **文档导入成功**
   - 返回 `entity_id`
   - `total_documents > 0`
   - `total_chunks > 0`

3. **语义检索返回结果**
   - 返回 `similarity > 0.5`
   - 返回 `source_url`
   - 返回 `version`
   - 返回 `chunk_text`

4. **审批流程完整**
   - 创建审批请求成功
   - 审批执行成功
   - 状态变更记录在审计日志

5. **审计追踪可查**
   - `approval_requests` 表有记录
   - `operation_audit_log` 表有记录
   - 状态为 `executed`

### ⚠️ 已知限制

1. **向量检索效率**
   - 当前：Python 内存中全量扫描
   - 原因：OpenTenBase 不支持 pgvector
   - 影响：文档 <500 时可接受
   - 后续：考虑外部向量库

2. **操作执行模拟**
   - 当前：模拟执行（返回成功）
   - 原因：需要实现安全的 SQL 执行器
   - 后续：实现参数化执行 + 超时控制

3. **LLM 推理简化**
   - 当前：硬编码诊断结果
   - 原因：先验证流程
   - 后续：接入真实 DeepSeek API

## 预期输出

```
AIOps 最小可验证闭环 (MVP)
================================================================================

[Step 0] Testing database connection...
✅ Connected to: postgres

[Step 1] Creating knowledge base tables...
✅ Knowledge base schema created

[Step 2] Importing test document...
✅ Document imported: a1b2c3d4-...

[Step 3] Testing semantic search...
✅ Search found result:
   Title: 主从复制延迟诊断 (测试文档)
   Similarity: 0.847
   Source: https://github.com/OpenTenBase/OpenTenBase/wiki
   Version: 1.0
   Chunk: 主从复制延迟是指主库的事务在从库上同步的时间差...

[Step 4] Simulating AI diagnosis...
✅ AI Diagnosis:
   Issue: 主从复制延迟达到 15 秒
   Root Cause: 从库磁盘 IO 饱和
   Evidence: 检测到 iowait 高达 85%
   Knowledge Ref: 主从复制延迟诊断 (测试文档)
   Recommended: analyze_table

[Step 5] Creating approval request...
✅ Approval request created: req-xyz-...

[Step 6] Simulating human approval...
✅ Operation approved and executed

[Step 7] Checking audit trail...
✅ Audit record:
   Operation: analyze_table
   Status: executed
   Reviewed by: dba_user
   Executed at: 2026-11-22 16:30:45

================================================================================
Final Statistics
================================================================================

Knowledge Base:
  Documents: 1
  Chunks: 3

Approval System:
  Pending requests: 0
  Audit log entries: 1

================================================================================
✅ MVP Closed-Loop COMPLETE!
================================================================================

Verified:
  ✓ Knowledge base operational
  ✓ Document import working
  ✓ Semantic search functional
  ✓ AI diagnosis simulation
  ✓ Approval workflow functional
  ✓ Audit trail recorded
```

## 失败排查

### 问题1: 数据库连接失败
```
❌ Database connection failed
```

**解决**:
```bash
# 检查容器
docker ps | grep otb

# 启动容器
docker start otb-node1 otb-node2

# 启动 OpenTenBase
docker exec -u opentenbase otb-node1 bash -lc 'cd /data/opentenbase/opentenbase_ctl && /data/opentenbase/install/opentenbase_bin_v5.0/bin/opentenbase_ctl start -c opentenbase_config.ini'
```

### 问题2: 表创建失败 (default group)
```
❌ Schema creation failed: default group not defined
```

**解决**: 已在 `knowledge_base.py` 中修复，使用 `DISTRIBUTE BY SHARD(entity_id)`

### 问题3: Embedding API 失败
```
❌ Failed to generate embedding
```

**解决**: 检查 `.env` 文件中的 `EMBEDDING_API_KEY`

## 下一步

### 完成闭环后
1. ✅ 增加更多官方文档
2. ✅ 接入真实 LLM 推理
3. ✅ 实现安全的 SQL 执行器
4. ✅ 添加执行后验证
5. ✅ 构建 Web UI

### 不做的事
- ❌ 在闭环未验证前扩充文档
- ❌ 在表未创建前导入大量数据
- ❌ 在流程未通前优化性能

---

**更新时间**: 2026-11-22  
**状态**: 🟡 等待验证  
**优先级**: P0 - 必须先通过此测试
