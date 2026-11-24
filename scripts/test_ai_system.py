#!/usr/bin/env python3
"""
AI Diagnostic System Integration Test

Tests the complete workflow:
1. Knowledge base (embedding + search)
2. Diagnostic memory (save + recall)
3. AI diagnosis (with LLM)
4. Approval workflow
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector
from backend.ai.embedding_client import EmbeddingClient
from backend.ai.knowledge_base import KnowledgeBase
from backend.ai.diagnostic_memory import DiagnosticMemory
from backend.ai.llm_client import DeepSeekClient
from backend.security.permissions import ApprovalWorkflow, OperationRegistry
from backend.engines.ai_diagnostic_engine import AIDiagnosticEngine

print("=" * 70)
print("OpenTenBase AIOps - AI Diagnostic System Test")
print("=" * 70)

# Initialize components
print("\n[1/7] Loading configuration...")
config = Config()
print(f"   DB: {config.DB_HOST}:{config.DB_PORT}")
print(f"   Embedding Model: {config.EMBEDDING_MODEL}")
print(f"   LLM Model: {config.DEEPSEEK_MODEL}")

# Database connection
print("\n[2/7] Connecting to database...")
db_connector = OpenTenBaseConnector(config)
status = db_connector.test_connection()
if status['connected']:
    print(f"   ✓ Connected: {status.get('database')}")
else:
    print(f"   ✗ Failed: {status.get('error')}")
    sys.exit(1)

# Embedding client
print("\n[3/7] Testing embedding service...")
embedding_client = EmbeddingClient(config)
embed_status = embedding_client.test_connection()
if embed_status['status'] == 'success':
    print(f"   ✓ Embedding service OK: {embed_status['dimension']} dimensions")
else:
    print(f"   ✗ Embedding service failed: {embed_status.get('error')}")

# Initialize systems
print("\n[4/7] Initializing AI systems...")
knowledge_base = KnowledgeBase(db_connector, embedding_client)
print("   ✓ Knowledge base initialized")

memory_system = DiagnosticMemory(db_connector, embedding_client)
print("   ✓ Memory system initialized")

approval_workflow = ApprovalWorkflow(db_connector)
print("   ✓ Approval workflow initialized")

llm_client = DeepSeekClient(config)
print("   ✓ LLM client initialized")

diagnostic_engine = AIDiagnosticEngine(
    db_connector,
    llm_client,
    memory_system,
    knowledge_base,
    approval_workflow,
    config
)
print("   ✓ Diagnostic engine initialized")

# Test 1: Add sample knowledge
print("\n[5/7] Testing knowledge base...")
sample_doc = """
OpenTenBase 主从复制延迟问题排查

常见原因：
1. 从库磁盘 IO 饱和
2. 网络带宽不足
3. 大事务导致的延迟
4. wal_sender/wal_receiver 配置问题

解决方案：
1. 检查从库磁盘使用率和 IO 等待
2. 使用 SELECT * FROM pg_stat_replication 查看延迟
3. 优化大事务，分批提交
4. 调整 max_wal_senders 参数
"""

doc_id = knowledge_base.add_document(
    title="主从复制延迟排查指南",
    content=sample_doc,
    category="troubleshooting",
    source_url="https://github.com/OpenTenBase/OpenTenBase/wiki",
    version="1.0"
)

if doc_id:
    print(f"   ✓ Added knowledge document: {doc_id}")

    # Search test
    results = knowledge_base.search("主从延迟很高怎么办", top_k=2)
    if results:
        print(f"   ✓ Search found {len(results)} results")
        print(f"     Top result similarity: {results[0]['similarity']:.3f}")
else:
    print("   ✗ Failed to add document")

# Test 2: Add sample diagnostic case
print("\n[6/7] Testing memory system...")
case_id = memory_system.save_case(
    symptoms="主从复制延迟突然增加到 15 秒",
    root_cause="从库磁盘 IO 饱和 (85% iowait)",
    solution="执行 VACUUM 清理表膨胀，扩容磁盘",
    metrics_snapshot={'replication_lag': 15, 'iowait': 85},
    effectiveness=0.9,
    tags=['replication', 'performance', 'disk'],
    created_by='test'
)

if case_id:
    print(f"   ✓ Saved diagnostic case: {case_id}")

    # Recall test
    similar = memory_system.recall_similar_cases("主从延迟太高", top_k=2)
    if similar:
        print(f"   ✓ Recalled {len(similar)} similar cases")
        print(f"     Top case similarity: {similar[0]['similarity']:.3f}")
        print(f"     Effectiveness: {similar[0]['effectiveness']:.2f}")
else:
    print("   ✗ Failed to save case")

# Test 3: Full diagnostic workflow
print("\n[7/7] Testing AI diagnostic engine...")
print("   Running diagnosis for: '连接数接近上限，性能下降'\n")

try:
    result = diagnostic_engine.diagnose(
        issue_description="连接数接近上限，已达到 90%，查询响应变慢",
        user_id="test_user"
    )

    if 'error' in result:
        print(f"   ✗ Diagnosis failed: {result['error']}")
    else:
        print(f"   ✓ Diagnosis completed")
        print(f"     Diagnosis ID: {result['diagnosis_id']}")
        print(f"     Confidence: {result['confidence']:.2f}")
        print(f"     Execution time: {result['execution_time_ms']}ms")

        diagnosis = result.get('diagnosis', {})
        print(f"\n   Root cause: {diagnosis.get('root_cause', 'N/A')}")
        print(f"   Risk level: {diagnosis.get('risk_level', 'N/A')}")

        solutions = diagnosis.get('solutions', [])
        print(f"   Solutions: {len(solutions)}")

        action_plan = result.get('action_plan', [])
        print(f"   Action plan: {len(action_plan)} actions")

        for i, action in enumerate(action_plan[:3], 1):
            status_icon = "⚠️" if action['requires_approval'] else "✓"
            print(f"     {status_icon} Action {i}: {action['operation']}")
            if action.get('approval_request_id'):
                print(f"       Approval request: {action['approval_request_id']}")

except Exception as e:
    print(f"   ✗ Diagnosis error: {e}")
    import traceback
    traceback.print_exc()

# Statistics
print("\n" + "=" * 70)
print("System Statistics")
print("=" * 70)

kb_stats = knowledge_base.get_statistics()
print(f"\nKnowledge Base:")
print(f"  Documents: {kb_stats.get('total_documents', 0)}")
print(f"  Chunks: {kb_stats.get('total_chunks', 0)}")

mem_stats = memory_system.get_statistics()
print(f"\nDiagnostic Memory:")
print(f"  Total cases: {mem_stats.get('total_cases', 0)}")
print(f"  Avg effectiveness: {mem_stats.get('avg_effectiveness', 0):.2f}")

pending_approvals = approval_workflow.get_pending_requests(limit=10)
print(f"\nApproval Workflow:")
print(f"  Pending requests: {len(pending_approvals)}")

print("\n" + "=" * 70)
print("✓ All tests completed!")
print("=" * 70)
print("\nNext steps:")
print("  1. Add more knowledge documents (official docs)")
print("  2. Build up diagnostic case history")
print("  3. Review and approve pending operations")
print("  4. Integrate with Web UI")
