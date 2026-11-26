#!/usr/bin/env python3
"""Measure read-only health collection latency against the configured cluster."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from math import ceil
from pathlib import Path
import statistics
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.collectors.readonly_health import ReadonlyHealthCollector
from backend.utils.config import Config


def _nearest_rank(values, percentile):
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _summarize(results):
    durations = [result["duration_ms"] for result in results]
    status_counts = {}
    errors_by_check = {}
    errors_by_sqlstate = {}
    for result in results:
        status = result["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        for check, error in result["errors"].items():
            errors_by_check[check] = errors_by_check.get(check, 0) + 1
            sqlstate = error.get("sqlstate")
            if sqlstate:
                errors_by_sqlstate[sqlstate] = errors_by_sqlstate.get(sqlstate, 0) + 1
    return {
        "runs": len(results),
        "error_count": sum(len(result["errors"]) for result in results),
        "status_counts": status_counts,
        "median_ms": round(statistics.median(durations), 2),
        "p95_ms_nearest_rank": round(_nearest_rank(durations, 0.95), 2),
        "max_ms": round(max(durations), 2),
        "errors_by_check": errors_by_check,
        "errors_by_sqlstate": errors_by_sqlstate,
    }


def _collect(config, run_number):
    started = time.perf_counter()
    try:
        result = ReadonlyHealthCollector(config).collect()
    except Exception as error:
        return {
            "run": run_number,
            "status": "error",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "errors": {
                "collector": {
                    "type": type(error).__name__,
                    "sqlstate": getattr(error, "pgcode", None),
                }
            },
        }
    return {
        "run": run_number,
        "status": result["status"],
        "duration_ms": result["collection_duration_ms"],
        "errors": {
            check: {
                "type": error.get("type"),
                "sqlstate": error.get("sqlstate"),
            }
            for check, error in result["errors"].items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10, help="Serial samples, from 1 to 100")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent readers, from 1 to 16")
    args = parser.parse_args()
    if not 1 <= args.runs <= 100:
        parser.error("--runs must be between 1 and 100")
    if not 1 <= args.concurrency <= 16:
        parser.error("--concurrency must be between 1 and 16")

    config = Config()
    started_at = datetime.now(timezone.utc)
    serial = [_collect(config, run) for run in range(1, args.runs + 1)]

    concurrent_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        concurrent = list(executor.map(
            lambda run: _collect(config, run),
            range(1, args.concurrency + 1),
        ))
    concurrent_wall_ms = round((time.perf_counter() - concurrent_started) * 1000, 2)

    report = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "target": config.audit_target,
        "limits": {
            "statement_timeout_ms": config.AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS,
            "lock_timeout_ms": config.AIOPS_COLLECTION_LOCK_TIMEOUT_MS,
        },
        "serial": {
            **_summarize(serial),
            "samples": serial,
        },
        "concurrent": {
            "workers": args.concurrency,
            "wall_clock_ms": concurrent_wall_ms,
            **_summarize(concurrent),
            "samples": concurrent,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
