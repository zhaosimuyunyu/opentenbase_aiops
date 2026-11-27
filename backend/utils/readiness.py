def build_readiness(database_status, metadata_status, capabilities=None):
    components = {
        "opentenbase": database_status,
        "metadata_database": metadata_status,
    }
    ready = all(component.get("connected") is True for component in components.values())
    return {
        "status": "ready" if ready else "not_ready",
        "api": "healthy" if ready else "degraded",
        "components": components,
        "capabilities": capabilities or {},
    }
