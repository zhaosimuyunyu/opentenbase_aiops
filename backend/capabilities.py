"""Verified operation boundary shared by the API and integration clients."""


CAPABILITIES = {
    "audit": {
        "readonly_health": True,
        "readonly_lock": True,
        "pg_unlock_extension_probe": True,
        "sse_progress": True,
    },
    "knowledge": {
        "pgvector": True,
        "official_sources": True,
        "tool_name": "search_knowledge",
    },
    "repairs": {
        "layered_approval": True,
        "program_review": True,
        "model_review": True,
        "independent_safety_agent": True,
        "human_approval": True,
        "verified_executors": ["analyze_table"],
        "suggestion_only": [
            "create_index", "vacuum_table", "reindex", "kill_query",
            "kill_connection", "alter_config",
        ],
        "automatic_prepared_transaction_resolution": False,
    },
}
