#!/usr/bin/env python3
"""Create, write, read and remove an isolated OpenTenBase SHARD demo table."""
import json
import uuid

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tools.execute_sql_tool import execute_sql


def require_success(action, result):
    if not result.get("success"):
        raise RuntimeError(f"{action} failed: {result.get('error')}")
    return {
        "action": action,
        "success": True,
        "command_tag": result.get("command_tag"),
        "row_count": result.get("row_count"),
        "execution_time_ms": result.get("execution_time_ms"),
        "audit_recorded": result.get("audit_recorded"),
    }


async def main():
    table = f"public.aiops_course_probe_{uuid.uuid4().hex[:10]}"
    results = []
    created = False
    try:
        result = await execute_sql(
            f"CREATE TABLE {table} (id bigint PRIMARY KEY, note text) "
            "DISTRIBUTE BY SHARD(id) TO GROUP default_group"
        )
        results.append(require_success("create_shard_table", result))
        created = True

        result = await execute_sql(
            f"INSERT INTO {table} (id,note) VALUES "
            "(101,'course-demo-alpha'),(102,'course-demo-beta')"
        )
        results.append(require_success("insert_two_rows", result))

        result = await execute_sql(
            f"SELECT count(*) AS total,min(id) AS min_id,max(id) AS max_id FROM {table}"
        )
        require_success("verify_rows", result)
        rows = result.get("rows") or []
        if not rows or rows[0].get("total") != 2:
            raise RuntimeError(f"Unexpected verification result: {rows}")
        results.append({"action": "verify_rows", "success": True, "rows": rows,
                        "audit_recorded": result.get("audit_recorded")})
    finally:
        if created:
            drop_result = await execute_sql(f"DROP TABLE IF EXISTS {table}")
            results.append(require_success("drop_demo_table", drop_result))

    verify_cleanup = await execute_sql(f"SELECT to_regclass('{table}') AS remaining_table")
    require_success("verify_cleanup", verify_cleanup)
    remaining = (verify_cleanup.get("rows") or [{}])[0].get("remaining_table")
    if remaining is not None:
        raise RuntimeError(f"Demo table remains after cleanup: {remaining}")
    results.append({"action": "verify_cleanup", "success": True,
                    "remaining_table": remaining,
                    "audit_recorded": verify_cleanup.get("audit_recorded")})
    print(json.dumps({"status": "passed", "table": table, "steps": results},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
