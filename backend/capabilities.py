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
    },
    "knowledge": {
        "pgvector": True,
        "official_sources": True,
        "tool_name": "search_knowledge",
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
        "suggestion_only": [
            "create_index", "vacuum_table", "reindex", "kill_query",
            "kill_connection", "alter_config",
        ],
        "automatic_prepared_transaction_resolution": False,
    },
}
