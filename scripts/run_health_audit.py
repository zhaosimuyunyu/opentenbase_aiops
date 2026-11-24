#!/usr/bin/env python3
"""Run one read-only health audit and print its persisted audit ID."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engines.readonly_audit_engine import ReadonlyAuditEngine


async def main():
    result = await ReadonlyAuditEngine().run_health_audit()
    output = {
        "audit_id": result["audit_id"],
        "audit_type": result["audit_type"],
        "risk_level": result["risk_level"],
        "collection_status": result["evidence"]["collection_status"],
        "findings": result["findings"],
        "tool_called": result["tool_called"],
        "analysis_fallback": result["analysis_fallback"],
        "knowledge_ref_count": len(result["knowledge_refs"]),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
