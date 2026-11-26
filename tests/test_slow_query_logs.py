import csv
import io
import unittest
from datetime import datetime, timedelta, timezone

from backend.collectors.slow_query_logs import parse_slow_query_csv


class SlowQueryLogTests(unittest.TestCase):
    def make_record(self, *, logged_at, message, pid="42", application_name="app"):
        record = [""] * 27
        record[0] = logged_at
        record[2] = "opentenbase"
        record[3] = "postgres"
        record[4] = pid
        record[11] = "SELECT"
        record[15] = "LOG"
        record[17] = message
        record[26] = application_name
        buffer = io.StringIO()
        csv.writer(buffer).writerow(record)
        return buffer.getvalue()

    def test_reads_recent_duration_statement_records(self):
        contents = self.make_record(
            logged_at="2026-11-26 14:35:00.250 CST",
            message="duration: 12015.690 ms  statement: SELECT pg_sleep(12)",
            pid="6073",
            application_name="course-demo",
        )
        reference_time = datetime(
            2026, 11, 26, 14, 40, tzinfo=timezone(timedelta(hours=8))
        )

        rows = parse_slow_query_csv(
            contents,
            node_name="cn0001",
            reference_time=reference_time,
            lookback_seconds=600,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["node_name"], "cn0001")
        self.assertEqual(rows[0]["pid"], 6073)
        self.assertEqual(rows[0]["application_name"], "course-demo")
        self.assertEqual(rows[0]["duration_ms"], 12015.69)
        self.assertEqual(rows[0]["query"], "SELECT pg_sleep(12)")
        self.assertEqual(rows[0]["source"], "server_csv_log")

    def test_ignores_old_non_duration_and_empty_records(self):
        reference_time = datetime(
            2026, 11, 26, 14, 40, tzinfo=timezone(timedelta(hours=8))
        )
        contents = "".join([
            self.make_record(
                logged_at="2026-11-26 13:00:00 CST",
                message="duration: 20000 ms  statement: SELECT old_query()",
            ),
            self.make_record(
                logged_at="2026-11-26 14:35:00 CST",
                message="statement completed",
            ),
            self.make_record(
                logged_at="2026-11-26 14:36:00 CST",
                message="duration: 12000 ms  statement: ",
            ),
        ])

        rows = parse_slow_query_csv(
            contents,
            node_name="dn0001",
            reference_time=reference_time,
            lookback_seconds=600,
        )

        self.assertEqual(rows, [])

    def test_skips_partial_csv_record_before_parsing_log_tail(self):
        record = self.make_record(
            logged_at="2026-11-26 14:35:00 CST",
            message="duration: 12000 ms  statement: SELECT pg_sleep(12)",
        )
        contents = 'partial,"truncated value\n' + record
        reference_time = datetime(
            2026, 11, 26, 14, 40, tzinfo=timezone(timedelta(hours=8))
        )

        rows = parse_slow_query_csv(
            contents,
            node_name="cn0001",
            reference_time=reference_time,
            lookback_seconds=600,
            partial_file=True,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["query"], "SELECT pg_sleep(12)")

    def test_collector_excludes_old_records_and_reports_node_read_errors(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from backend.collectors.slow_query_logs import SlowQueryLogCollector

        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "reference_time": datetime(
                2026, 11, 26, 14, 40, tzinfo=timezone(timedelta(hours=8))
            )
        }
        cursor.fetchall.return_value = [{
            "file": "postgresql-Thursday-14.csv",
            "contents": self.make_record(
                logged_at="2026-11-26 13:00:00 CST",
                message="duration: 20000 ms  statement: SELECT old_query()",
            ),
            "partial_file": False,
        }]
        node = {
            "node_name": "cn0001", "node_type": "C",
            "node_host": "cn1", "node_port": 11003,
        }
        config = SimpleNamespace(
            DB_NAME="postgres", DB_USER="opentenbase", DB_PASSWORD="",
            AIOPS_SLOW_QUERY_LOG_LOOKBACK_SECONDS=600,
        )

        with patch("backend.collectors.slow_query_logs.psycopg2.connect", return_value=connection):
            rows, errors = SlowQueryLogCollector(config).collect([node])

        self.assertEqual(rows, [])
        self.assertEqual(errors, {})
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
