"""
AI Diagnostic Engine - Production Grade

Integrates:
- Historical case memory
- Knowledge base retrieval
- LLM reasoning
- Permission-aware action planning
- Audit logging
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from ..utils.logger import setup_logger
from ..utils.db_connector import OpenTenBaseConnector
from ..utils.config import Config
from ..ai.llm_client import DeepSeekClient
from ..ai.diagnostic_memory import DiagnosticMemory
from ..ai.knowledge_base import KnowledgeBase
from ..security.permissions import OperationRegistry, ApprovalWorkflow
from ..collectors.cluster import ClusterCollector
from ..collectors.performance import PerformanceCollector

logger = setup_logger(__name__)


class AIDiagnosticEngine:
    """
    AI-powered diagnostic engine with memory and approval system

    Features:
    - Similar case recall from historical memory
    - Knowledge base search for official docs
    - Multi-step reasoning with LLM
    - Permission-aware action planning
    - Automatic audit logging
    """

    def __init__(
        self,
        db_connector: OpenTenBaseConnector,
        llm_client: DeepSeekClient,
        memory_system: DiagnosticMemory,
        knowledge_base: KnowledgeBase,
        approval_workflow: ApprovalWorkflow,
        config: Optional[Config] = None
    ):
        self.db = db_connector
        self.llm = llm_client
        self.memory = memory_system
        self.knowledge = knowledge_base
        self.approval = approval_workflow
        self.config = config or Config()

        # Data collectors
        self.cluster_collector = ClusterCollector(db_connector)
        self.perf_collector = PerformanceCollector(db_connector, self.config)

    def diagnose(
        self,
        issue_description: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Complete diagnostic workflow

        Args:
            issue_description: Problem description
            user_id: User requesting diagnosis

        Returns:
            Comprehensive diagnosis with action plan
        """
        start_time = datetime.now()

        try:
            logger.info(f"Starting diagnosis for: {issue_description}")

            # Step 1: Collect current cluster state
            logger.info("Step 1: Collecting cluster state...")
            current_state = self._collect_current_state()

            # Step 2: Recall similar historical cases
            logger.info("Step 2: Recalling similar cases...")
            similar_cases = self.memory.recall_similar_cases(
                issue_description,
                top_k=3,
                min_similarity=0.5
            )

            # Step 3: Search knowledge base
            logger.info("Step 3: Searching knowledge base...")
            relevant_docs = self.knowledge.search(
                issue_description,
                top_k=3,
                category='troubleshooting'
            )

            # Step 4: LLM-powered analysis
            logger.info("Step 4: AI analysis...")
            diagnosis = self._analyze_with_llm(
                issue_description,
                current_state,
                similar_cases,
                relevant_docs
            )

            # Step 5: Generate action plan
            logger.info("Step 5: Generating action plan...")
            action_plan = self._generate_action_plan(diagnosis, user_id)

            # Step 6: Calculate confidence
            confidence = self._calculate_confidence(
                diagnosis,
                similar_cases,
                relevant_docs
            )

            # Compile result
            result = {
                'diagnosis_id': self._generate_diagnosis_id(),
                'issue': issue_description,
                'timestamp': datetime.now().isoformat(),
                'diagnosis': diagnosis,
                'action_plan': action_plan,
                'similar_cases': similar_cases,
                'relevant_docs': relevant_docs,
                'current_state': current_state,
                'confidence': confidence,
                'execution_time_ms': int((datetime.now() - start_time).total_seconds() * 1000)
            }

            # Save to memory if confidence is high enough
            if confidence > 0.6:
                self._save_to_memory(result, user_id)

            logger.info(f"Diagnosis completed: confidence={confidence:.2f}")
            return result

        except Exception as e:
            logger.error(f"Diagnosis failed: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'issue': issue_description
            }

    def _collect_current_state(self) -> Dict[str, Any]:
        """Collect current cluster metrics"""
        try:
            cluster_data = self.cluster_collector.collect().get('data', {})
            perf_data = self.perf_collector.collect().get('data', {})

            return {
                'cluster': cluster_data,
                'performance': perf_data,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to collect state: {e}")
            return {}

    def _analyze_with_llm(
        self,
        issue: str,
        current_state: Dict,
        similar_cases: List[Dict],
        relevant_docs: List[Dict]
    ) -> Dict[str, Any]:
        """Use LLM for root cause analysis"""

        prompt = self._build_diagnostic_prompt(
            issue,
            current_state,
            similar_cases,
            relevant_docs
        )

        try:
            response = self.llm.chat([
                {"role": "system", "content": DIAGNOSTIC_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ])

            # Parse LLM response (expecting JSON)
            import json
            diagnosis = json.loads(response)

            return diagnosis

        except json.JSONDecodeError:
            # Fallback: return raw text if not JSON
            logger.warning("LLM returned non-JSON response")
            return {
                'root_cause': response,
                'risk_level': 'unknown',
                'solutions': [],
                'reasoning': response
            }
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return {
                'root_cause': 'Analysis failed',
                'error': str(e)
            }

    def _build_diagnostic_prompt(
        self,
        issue: str,
        current_state: Dict,
        similar_cases: List[Dict],
        relevant_docs: List[Dict]
    ) -> str:
        """Build comprehensive diagnostic prompt"""

        # Format current state
        cluster_summary = self._format_cluster_state(current_state)

        # Format similar cases
        cases_text = "\n".join([
            f"### 案例 {i+1} (相似度: {c['similarity']:.2f}, 有效性: {c['success_rate']:.2f})\n"
            f"症状: {c['symptoms']}\n"
            f"根因: {c['root_cause']}\n"
            f"解决方案: {c['solution']}\n"
            for i, c in enumerate(similar_cases[:3])
        ]) if similar_cases else "无相似历史案例"

        # Format docs
        docs_text = "\n".join([
            f"### 文档 {i+1} ({d['category']})\n"
            f"{d['chunk_text'][:300]}...\n"
            for i, d in enumerate(relevant_docs[:2])
        ]) if relevant_docs else "无相关文档"

        prompt = f"""
# OpenTenBase 数据库诊断任务

## 当前问题
{issue}

## 集群当前状态
{cluster_summary}

## 历史相似案例
{cases_text}

## 相关官方文档
{docs_text}

## 诊断要求

请作为 OpenTenBase 分布式数据库专家，完成以下诊断：

1. **根本原因分析**
   - 基于当前指标和日志
   - 考虑 OpenTenBase 分布式特性（GTM, CN, DN）
   - 参考历史案例但不盲从

2. **风险评估**
   - 评估风险等级: low | medium | high | critical
   - 说明潜在影响范围

3. **解决方案**
   - 按优先级排序（最安全、最有效的在前）
   - 每个方案包含：
     * 具体操作步骤
     * 可执行的 SQL/命令
     * 风险说明
     * 预期效果
     * 验证方法

4. **置信度评估**
   - 评估诊断置信度 (0-1)
   - 说明不确定的因素

## 输出格式（严格 JSON）

```json
{{
    "root_cause": "根本原因描述",
    "risk_level": "low|medium|high|critical",
    "solutions": [
        {{
            "priority": 1,
            "description": "方案描述",
            "operations": [
                {{
                    "operation": "operation_name",
                    "command": "具体命令或SQL",
                    "risk": "风险说明"
                }}
            ],
            "expected_outcome": "预期效果",
            "verification": "验证方法"
        }}
    ],
    "confidence": 0.85,
    "reasoning": "推理过程和依据",
    "uncertainties": ["不确定的因素1", "因素2"]
}}
```

注意事项：
- 只输出 JSON，不要有其他文字
- 优先推荐可逆、低风险的方案
- 如果不确定，诚实说明
- 考虑分布式数据库的特殊性
"""
        return prompt

    def _format_cluster_state(self, state: Dict) -> str:
        """Format cluster state for prompt"""
        if not state:
            return "状态信息收集失败"

        cluster = state.get('cluster', {})
        perf = state.get('performance', {})

        text = f"""
### 基础信息
- 节点数: {len(cluster.get('nodes', []))}
- 总连接数: {cluster.get('connections', {}).get('total', 'N/A')}
- 最大连接数: {cluster.get('connections', {}).get('max_connections', 'N/A')}
- 连接使用率: {cluster.get('connections', {}).get('usage_percent', 'N/A')}%

### 复制状态
- 复制连接数: {len(cluster.get('replication', []))}

### 性能指标
- 活跃锁数: {len(perf.get('locks', {}).get('all_locks', []))}
- 阻塞锁数: {perf.get('locks', {}).get('blocked_count', 0)}
- 长查询数: {len(perf.get('long_running_queries', []))}
"""
        return text

    def _generate_action_plan(
        self,
        diagnosis: Dict,
        user_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Generate permission-aware action plan"""

        action_plan = []

        for solution in diagnosis.get('solutions', []):
            for operation in solution.get('operations', []):
                op_name = operation.get('operation', 'unknown')

                # Check permission level
                requires_approval = OperationRegistry.require_approval(op_name)
                is_dangerous = OperationRegistry.is_dangerous(op_name)

                action = {
                    'action_id': self._generate_action_id(),
                    'operation': op_name,
                    'command': operation.get('command'),
                    'description': solution.get('description'),
                    'risk': operation.get('risk'),
                    'requires_approval': requires_approval,
                    'is_dangerous': is_dangerous,
                    'status': 'pending_approval' if requires_approval else 'ready',
                    'approval_request_id': None
                }

                # Auto-create approval request for operations requiring it
                if requires_approval:
                    try:
                        request_id = self.approval.request_approval(
                            operation=op_name,
                            parameters={'command': operation.get('command')},
                            ai_reasoning=diagnosis.get('reasoning', ''),
                            risk_assessment=operation.get('risk'),
                            created_by='ai_diagnostic_engine'
                        )
                        action['approval_request_id'] = request_id
                    except Exception as e:
                        logger.error(f"Failed to create approval request: {e}")
                        action['error'] = str(e)

                action_plan.append(action)

        return action_plan

    def _calculate_confidence(
        self,
        diagnosis: Dict,
        similar_cases: List[Dict],
        relevant_docs: List[Dict]
    ) -> float:
        """Calculate overall diagnostic confidence"""

        # Base confidence from LLM
        llm_confidence = diagnosis.get('confidence', 0.5)

        # Boost if we have similar cases
        case_boost = 0.0
        if similar_cases:
            avg_similarity = sum(c['similarity'] for c in similar_cases) / len(similar_cases)
            avg_effectiveness = sum(c['success_rate'] for c in similar_cases) / len(similar_cases)
            case_boost = (avg_similarity * avg_effectiveness) * 0.2

        # Boost if we have relevant docs
        doc_boost = 0.0
        if relevant_docs:
            avg_doc_similarity = sum(d['similarity'] for d in relevant_docs) / len(relevant_docs)
            doc_boost = avg_doc_similarity * 0.1

        # Combined confidence (capped at 0.95)
        confidence = min(llm_confidence + case_boost + doc_boost, 0.95)

        return confidence

    def _save_to_memory(self, result: Dict, user_id: Optional[str]):
        """Save successful diagnosis to memory"""
        try:
            diagnosis = result['diagnosis']

            # Extract primary solution
            solutions = diagnosis.get('solutions', [])
            primary_solution = solutions[0] if solutions else {'description': 'No solution'}

            self.memory.save_case(
                symptoms=result['issue'],
                root_cause=diagnosis.get('root_cause', 'Unknown'),
                solution=primary_solution.get('description', 'Unknown'),
                metrics_snapshot=result['current_state'],
                effectiveness=result['confidence'],
                tags=self._extract_tags(result['issue'], diagnosis),
                created_by=user_id or 'ai'
            )

        except Exception as e:
            logger.error(f"Failed to save to memory: {e}")

    def _extract_tags(self, issue: str, diagnosis: Dict) -> List[str]:
        """Extract relevant tags from issue and diagnosis"""
        tags = []

        # Keyword-based tagging
        keywords = {
            'replication': ['replication', 'lag', '主从', '延迟'],
            'performance': ['slow', 'performance', '慢', '性能'],
            'lock': ['lock', 'deadlock', '锁', '死锁'],
            'connection': ['connection', 'connect', '连接'],
            'disk': ['disk', 'io', '磁盘'],
            'memory': ['memory', 'oom', '内存']
        }

        text = (issue + ' ' + diagnosis.get('root_cause', '')).lower()

        for tag, words in keywords.items():
            if any(word in text for word in words):
                tags.append(tag)

        return tags or ['general']

    @staticmethod
    def _generate_diagnosis_id() -> str:
        """Generate unique diagnosis ID"""
        import uuid
        return f"diag_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _generate_action_id() -> str:
        """Generate unique action ID"""
        import uuid
        return f"action_{uuid.uuid4().hex[:8]}"


# System prompt for diagnostic LLM
DIAGNOSTIC_SYSTEM_PROMPT = """你是 OpenTenBase 分布式数据库的专家 DBA，具有以下能力：

**专业知识**：
- OpenTenBase 架构：GTM（全局事务管理器）、CN（协调节点）、DN（数据节点）
- 分布式事务、分片策略、跨节点查询优化
- PostgreSQL 10.x 核心特性
- 常见运维问题：复制延迟、锁冲突、性能瓶颈

**诊断原则**：
1. **数据驱动**：基于实际指标和日志，不要猜测
2. **安全优先**：推荐的操作必须是可逆的或低风险的
3. **分布式优先**：考虑分布式数据库的特殊性
4. **学习历史**：参考历史案例但不盲从
5. **可验证**：每个方案都给出验证方法

**输出要求**：
- 严格按照 JSON 格式输出
- 不要输出任何 JSON 之外的文字
- 包含完整的推理过程
- 给出具体可执行的命令
- 诚实评估置信度和不确定性

**风险意识**：
- 区分只读查询和写操作
- 标注每个操作的风险级别
- 优先推荐可逆操作
- 对于高风险操作，给出详细的影响说明
"""
