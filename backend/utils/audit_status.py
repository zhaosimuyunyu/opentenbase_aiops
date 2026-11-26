READONLY_AUDIT_TYPES = {"readonly_health_audit", "readonly_lock_audit"}


def normalize_audit_record(record):
    result = dict(record)
    if result.get("status") == "pending" and result.get("audit_type") in READONLY_AUDIT_TYPES:
        result["status"] = "completed"
    return result
