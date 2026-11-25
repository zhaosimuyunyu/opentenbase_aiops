"""Permission and Approval System"""
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
import re
from ..utils.logger import setup_logger
from ..utils.db_connector import OpenTenBaseConnector

logger = setup_logger(__name__)


class PermissionLevel(Enum):
    """Operation permission levels"""
    READ_ONLY = "read_only"        # Safe: queries, analysis
    SAFE_WRITE = "safe_write"      # Low risk: CREATE INDEX, ANALYZE
    DANGEROUS = "dangerous"         # High risk: DELETE, KILL, RESTART


class OperationRegistry:
    """
    Registry of all database operations with permission levels

    Design principle: Default-deny, explicit-allow
    """

    OPERATIONS = {
        "search_knowledge": {
            "level": PermissionLevel.READ_ONLY,
            "description": "Search the versioned operations knowledge base",
            "sql_pattern": "VECTOR SEARCH",
        },
        "get_database_locks": {
            "level": PermissionLevel.READ_ONLY,
            "description": "Read current lock and blocker evidence",
            "sql_pattern": "SELECT FROM pg_locks",
        },
        # === READ_ONLY operations (AI can execute automatically) ===
        "query_cluster_status": {
            "level": PermissionLevel.READ_ONLY,
            "description": "Query cluster nodes and status",
            "sql_pattern": "SELECT .* FROM pgxc_node"
        },
        "query_connections": {
            "level": PermissionLevel.READ_ONLY,
            "description": "Query active connections",
            "sql_pattern": "SELECT .* FROM pg_stat_activity"
        },
        "query_locks": {
            "level": PermissionLevel.READ_ONLY,
            "description": "Query lock information",
            "sql_pattern": "SELECT .* FROM pg_locks"
        },
        "explain_query": {
            "level": PermissionLevel.READ_ONLY,
            "description": "Get query execution plan",
            "sql_pattern": "EXPLAIN .*"
        },
        "query_replication": {
            "level": PermissionLevel.READ_ONLY,
            "description": "Query replication status",
            "sql_pattern": "SELECT .* FROM pg_stat_replication"
        },

        # === SAFE_WRITE operations (AI can suggest, requires approval) ===
        "create_index": {
            "level": PermissionLevel.SAFE_WRITE,
            "description": "Create database index",
            "sql_pattern": "CREATE INDEX .* ON .*",
            "risk": "May impact write performance temporarily, reversible"
        },
        "analyze_table": {
            "level": PermissionLevel.SAFE_WRITE,
            "description": "Update table statistics",
            "sql_pattern": "ANALYZE .*",
            "risk": "May lock table briefly, reversible"
        },
        "vacuum_table": {
            "level": PermissionLevel.SAFE_WRITE,
            "description": "Clean up dead tuples",
            "sql_pattern": "VACUUM .*",
            "risk": "May lock table, reversible"
        },
        "reindex": {
            "level": PermissionLevel.SAFE_WRITE,
            "description": "Rebuild index",
            "sql_pattern": "REINDEX .*",
            "risk": "Locks affected objects, reversible"
        },

        # === DANGEROUS operations (AI can only suggest, strict approval) ===
        "kill_query": {
            "level": PermissionLevel.DANGEROUS,
            "description": "Terminate running query",
            "sql_pattern": "SELECT pg_cancel_backend\\(.*\\)",
            "risk": "May interrupt critical operations, irreversible"
        },
        "kill_connection": {
            "level": PermissionLevel.DANGEROUS,
            "description": "Terminate client connection",
            "sql_pattern": "SELECT pg_terminate_backend\\(.*\\)",
            "risk": "Forcefully disconnect clients, irreversible"
        },
        "drop_index": {
            "level": PermissionLevel.DANGEROUS,
            "description": "Drop database index",
            "sql_pattern": "DROP INDEX .*",
            "risk": "May severely impact query performance, irreversible"
        },
        "alter_config": {
            "level": PermissionLevel.DANGEROUS,
            "description": "Modify server configuration",
            "sql_pattern": "ALTER SYSTEM SET .*",
            "risk": "May require restart, affects global behavior"
        },
    }

    RISK_KEYWORDS = re.compile(
        r"\b(drop|truncate|delete|update|insert|merge|alter|grant|revoke|create\s+role|"
        r"create\s+user|vacuum\s+full|reindex|pg_terminate_backend|pg_cancel_backend|"
        r"pg_clean_(execute|commit|rollback)|restart|shutdown|failover|switchover)\b",
        re.IGNORECASE,
    )

    @classmethod
    def classify(cls, operation_name: str, statement: str = "") -> Dict[str, Any]:
        """Return a deterministic execution policy. Unknown actions require a person."""
        operation = cls.get_operation(operation_name)
        matched = cls.RISK_KEYWORDS.search(statement or "")
        operation_keyword = cls.RISK_KEYWORDS.search((operation_name or "").replace("_", " "))
        matched = matched or operation_keyword
        if matched:
            return {
                "risk_level": "high",
                "requires_human_approval": True,
                "matched_keyword": matched.group(0),
                "reason": "Operation may change data, access, availability, or cluster state",
            }
        if operation is None:
            return {
                "risk_level": "unknown",
                "requires_human_approval": True,
                "matched_keyword": None,
                "reason": "Operation is not in the explicit registry",
            }
        if operation["level"] == PermissionLevel.DANGEROUS:
            return {
                "risk_level": "high",
                "requires_human_approval": True,
                "matched_keyword": matched.group(0) if matched else operation_name,
                "reason": "Operation may change data, access, availability, or cluster state",
            }
        if operation["level"] == PermissionLevel.READ_ONLY:
            return {
                "risk_level": "low",
                "requires_human_approval": False,
                "matched_keyword": None,
                "reason": "Registered read-only operation",
            }
        return {
            "risk_level": "moderate",
            "requires_human_approval": True,
            "matched_keyword": None,
            "reason": "Registered operation can affect database workload",
        }

    @classmethod
    def get_operation(cls, operation_name: str) -> Optional[Dict]:
        """Get operation definition"""
        return cls.OPERATIONS.get(operation_name)

    @classmethod
    def require_approval(cls, operation_name: str) -> bool:
        """Check if operation requires human approval"""
        return cls.classify(operation_name)["requires_human_approval"]

    @classmethod
    def is_dangerous(cls, operation_name: str) -> bool:
        """Check if operation is dangerous"""
        op = cls.OPERATIONS.get(operation_name)
        return op and op['level'] == PermissionLevel.DANGEROUS


class ApprovalWorkflow:
    """
    Human-in-the-loop approval system for AI operations

    Based on AgentX's authorization model but simplified for AIOps
    """

    def __init__(self, db_connector: OpenTenBaseConnector):
        self.db = db_connector
        self._ensure_schema()

    def _ensure_schema(self):
        """Create approval tables"""
        schema_sql = """
        -- Approval requests
        CREATE TABLE IF NOT EXISTS approval_requests (
            request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            operation TEXT NOT NULL,
            operation_level TEXT NOT NULL,  -- 'read_only' | 'safe_write' | 'dangerous'
            parameters JSONB NOT NULL,
            ai_reasoning TEXT,  -- Why AI suggested this
            risk_assessment TEXT,
            status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected' | 'executed'
            created_at TIMESTAMPTZ DEFAULT NOW(),
            created_by TEXT,  -- AI agent ID or user ID
            reviewed_at TIMESTAMPTZ,
            reviewed_by TEXT,
            review_comment TEXT,
            executed_at TIMESTAMPTZ,
            execution_result JSONB
        ) DISTRIBUTE BY REPLICATION TO GROUP default_group;

        -- Execution audit log
        CREATE TABLE IF NOT EXISTS operation_audit_log (
            log_id BIGSERIAL PRIMARY KEY,
            request_id UUID REFERENCES approval_requests(request_id),
            operation TEXT NOT NULL,
            parameters JSONB,
            executed_by TEXT,
            execution_time_ms INT,
            success BOOLEAN,
            result JSONB,
            error_message TEXT,
            executed_at TIMESTAMPTZ DEFAULT NOW()
        ) DISTRIBUTE BY REPLICATION TO GROUP default_group;

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_approval_operation ON approval_requests(operation);
        CREATE INDEX IF NOT EXISTS idx_audit_request ON operation_audit_log(request_id);
        CREATE INDEX IF NOT EXISTS idx_audit_time ON operation_audit_log(executed_at DESC);
        """

        try:
            with self.db.get_cursor(dict_cursor=False) as cursor:
                cursor.execute(schema_sql)
            logger.info("Approval system schema ensured")
        except Exception as e:
            logger.error(f"Failed to create approval schema: {e}")

    def request_approval(
        self,
        operation: str,
        parameters: Dict[str, Any],
        ai_reasoning: str,
        risk_assessment: Optional[str] = None,
        created_by: str = 'ai_agent'
    ) -> str:
        """
        Create approval request for AI-suggested operation

        Args:
            operation: Operation name
            parameters: Operation parameters
            ai_reasoning: AI's explanation
            risk_assessment: Risk analysis
            created_by: Creator identifier

        Returns:
            request_id
        """
        try:
            op_def = OperationRegistry.get_operation(operation)
            if not op_def:
                raise ValueError(f"Unknown operation: {operation}")

            result = self.db.execute_query("""
                INSERT INTO approval_requests
                (operation, operation_level, parameters, ai_reasoning, risk_assessment, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING request_id
            """, (
                operation,
                op_def['level'].value,
                parameters,
                ai_reasoning,
                risk_assessment or op_def.get('risk', 'Unknown risk'),
                created_by
            ), fetch_one=True)

            request_id = str(result['request_id'])
            logger.info(f"Created approval request: {request_id} for {operation}")

            # TODO: Send notification to admins (email, Slack, Web UI)

            return request_id

        except Exception as e:
            logger.error(f"Failed to create approval request: {e}")
            raise

    def approve(
        self,
        request_id: str,
        reviewer: str,
        comment: Optional[str] = None
    ) -> bool:
        """
        Approve and execute operation

        Args:
            request_id: Request ID
            reviewer: Reviewer identifier
            comment: Optional review comment

        Returns:
            Success status
        """
        try:
            # Update approval status
            self.db.execute_query("""
                UPDATE approval_requests
                SET status = 'approved',
                    reviewed_at = NOW(),
                    reviewed_by = %s,
                    review_comment = %s
                WHERE request_id = %s AND status = 'pending'
            """, (reviewer, comment, request_id))

            # Get request details
            request = self.db.execute_query("""
                SELECT operation, parameters, operation_level
                FROM approval_requests
                WHERE request_id = %s
            """, (request_id,), fetch_one=True)

            if not request:
                raise ValueError(f"Request not found or already processed: {request_id}")

            # Execute operation (with safety checks)
            result = self._execute_operation(request)

            # Update execution status
            self.db.execute_query("""
                UPDATE approval_requests
                SET status = 'executed',
                    executed_at = NOW(),
                    execution_result = %s
                WHERE request_id = %s
            """, (result, request_id))

            # Log to audit trail
            self._log_execution(request_id, request, result, reviewer)

            logger.info(f"Executed approved request: {request_id}")
            return result.get('success', False)

        except Exception as e:
            logger.error(f"Failed to approve/execute: {e}")
            # Mark as failed
            self.db.execute_query("""
                UPDATE approval_requests
                SET status = 'rejected',
                    reviewed_at = NOW(),
                    reviewed_by = %s,
                    review_comment = %s
                WHERE request_id = %s
            """, (reviewer, f"Execution error: {str(e)}", request_id))
            return False

    def reject(
        self,
        request_id: str,
        reviewer: str,
        reason: str
    ) -> bool:
        """Reject approval request"""
        try:
            self.db.execute_query("""
                UPDATE approval_requests
                SET status = 'rejected',
                    reviewed_at = NOW(),
                    reviewed_by = %s,
                    review_comment = %s
                WHERE request_id = %s AND status = 'pending'
            """, (reviewer, reason, request_id))

            logger.info(f"Rejected request: {request_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to reject: {e}")
            return False

    def _execute_operation(self, request: Dict) -> Dict[str, Any]:
        """
        Execute approved operation with safety checks

        Returns operation result
        """
        operation = request['operation']
        parameters = request['parameters']

        start_time = datetime.now()

        try:
            # This legacy registry has no database executor. Never report a
            # simulated success as a real change. The production repair API
            # uses RepairWorkflow with operation-specific verification.
            result = {
                'success': False,
                'operation': operation,
                'parameters': parameters,
                'error': 'No operation executor is registered for this legacy workflow'
            }

            execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            result['execution_time_ms'] = execution_time_ms

            return result

        except Exception as e:
            return {
                'success': False,
                'operation': operation,
                'error': str(e)
            }

    def _log_execution(
        self,
        request_id: str,
        request: Dict,
        result: Dict,
        executed_by: str
    ):
        """Log operation execution to audit trail"""
        try:
            self.db.execute_query("""
                INSERT INTO operation_audit_log
                (request_id, operation, parameters, executed_by, execution_time_ms, success, result, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                request_id,
                request['operation'],
                request['parameters'],
                executed_by,
                result.get('execution_time_ms', 0),
                result.get('success', False),
                result,
                result.get('error')
            ))
        except Exception as e:
            logger.error(f"Failed to log execution: {e}")

    def get_pending_requests(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get pending approval requests"""
        try:
            return self.db.execute_query("""
                SELECT *
                FROM approval_requests
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
        except Exception as e:
            logger.error(f"Failed to get pending requests: {e}")
            return []

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get specific approval request"""
        try:
            result = self.db.execute_query("""
                SELECT * FROM approval_requests WHERE request_id = %s
            """, (request_id,), fetch_one=True)
            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to get request: {e}")
            return None

    def get_audit_log(
        self,
        operation: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get operation audit log"""
        try:
            sql = "SELECT * FROM operation_audit_log"
            params = []

            if operation:
                sql += " WHERE operation = %s"
                params.append(operation)

            sql += " ORDER BY executed_at DESC LIMIT %s"
            params.append(limit)

            return self.db.execute_query(sql, tuple(params))
        except Exception as e:
            logger.error(f"Failed to get audit log: {e}")
            return []
