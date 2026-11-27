#!/usr/bin/env python3
"""Redact legacy SQL literals from persisted AIOps evidence JSON."""
import argparse
import json

from backend.utils.operations_store import OperationsStore
from backend.utils.sql_redaction_migration import redact_persisted_query_literals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="write redacted JSON records; without this flag only report the dry run",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    store = OperationsStore()
    try:
        result = redact_persisted_query_literals(
            store, apply=args.apply, batch_size=args.batch_size
        )
    finally:
        store.close()

    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **result}, indent=2))
    if args.apply and result["concurrent_changes"]:
        raise SystemExit(
            "Some rows changed concurrently and were not overwritten. Rerun the migration to rescan."
        )


if __name__ == "__main__":
    main()
