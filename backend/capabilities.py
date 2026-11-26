"""Verified operation boundary shared by the API and integration clients."""


CAPABILITIES = {
    "audit": {
        "readonly_health": True,
        "readonly_lock": True,
        "pg_unlock_extension_probe": True,
        "sse_progress": True,
        "sql_static_rules": True,
        "readonly_explain": True,
        "distributed_cn_dn_checks": True,
        "alertmanager_agent_trigger": True,
        "alert_task_status": True,
    },
    "knowledge": {
        "pgvector": True,
        "official_sources": True,
        "tool_name": "search_knowledge",
    },
    "interactive_agent": {
        "multi_turn_tool_use": True,
        "live_runtime_context": True,
        "live_topology_tool": True,
        "sql_execution_audit": True,
        "all_knowledge_categories_searchable": True,
        "unrestricted_sql_tool": True,
        "sql_operation_approval_required": False,
        "sql_scope": "current_database_login_privileges",
        "direct_cn_dn_sql": True,
        "execution_audit_records": "target,sql_sha256,command_tag,status,row_count,sqlstate,duration",
        "audit_stores_sql_text": False,
    },
    "repairs": {
        "risk_policy": True,
        "low_risk_readonly_auto_execution": True,
        "unknown_operations_default_to_human": True,
        "destructive_keyword_detection": True,
        "layered_approval": False,
        "program_review": False,
        "model_review": False,
        "independent_safety_agent": False,
        "human_approval": True,
        "verified_executors": ["analyze_table"],
        "scheduled_auto_repair": {
            "configurable": True,
            "default_enabled": False,
            "executor": "analyze_table",
            "requires_explicit_targets": True,
            "requires_full_health_audit": True,
            "requires_admin_function_allowlist": True,
        },
        "suggestion_only": [
            "create_index", "vacuum_table", "reindex", "cancel_query", "kill_query",
            "kill_connection", "alter_config",
        ],
        "automatic_prepared_transaction_resolution": False,
    },
}
