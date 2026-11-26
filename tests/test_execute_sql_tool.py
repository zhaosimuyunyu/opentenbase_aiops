import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.tools.execute_sql_tool import execute_sql


class ExecuteSqlToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_node_execution_uses_isolated_target_config(self):
        config = SimpleNamespace(
            DB_HOST="cn", DB_PORT=11003, DB_NAME="postgres", DB_USER="admin", DB_PASSWORD="secret"
        )
        discovery = MagicMock()
        discovery.connect.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            "D", "dn-host", 11006,
        )
        target = MagicMock()
        target_connection = target.connect.return_value
        target_connection.cursor.return_value.__enter__.return_value.description = None
        target_connection.cursor.return_value.__enter__.return_value.statusmessage = "ANALYZE"
        target_connection.cursor.return_value.__enter__.return_value.rowcount = -1

        with patch("backend.tools.execute_sql_tool.Config", return_value=config), patch(
            "backend.tools.execute_sql_tool.OpenTenBaseConnector", side_effect=[discovery, target]
        ) as connector_factory, patch(
            "backend.tools.execute_sql_tool._record_execution", return_value=True
        ) as audit:
            result = await execute_sql("ANALYZE public.orders", node_name="dn0001")

        target_config = connector_factory.call_args_list[1].args[0]
        self.assertEqual((target_config.DB_HOST, target_config.DB_PORT), ("dn-host", 11006))
        self.assertEqual((config.DB_HOST, config.DB_PORT), ("cn", 11003))
        self.assertTrue(result["success"])
        self.assertEqual(audit.call_args.args[-1], "dn0001")

    async def test_gtm_node_is_not_sent_postgresql_sql(self):
        config = SimpleNamespace(
            DB_HOST="cn", DB_PORT=11003, DB_NAME="postgres", DB_USER="admin", DB_PASSWORD="secret"
        )
        discovery = MagicMock()
        discovery.connect.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            "G", "gtm-host", 11000,
        )
        with patch("backend.tools.execute_sql_tool.Config", return_value=config), patch(
            "backend.tools.execute_sql_tool.OpenTenBaseConnector", return_value=discovery
        ):
            result = await execute_sql("SELECT 1", node_name="gtm0001")
        self.assertFalse(result["success"])
        self.assertIn("native protocol", result["error"])

    async def test_executes_sql_and_records_digest_without_sql_text(self):
        connector = MagicMock()
        connection = connector.connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [("value",)]
        cursor.fetchall.return_value = [(1,)]
        cursor.statusmessage = "SELECT 1"
        cursor.rowcount = 1
        config = SimpleNamespace(DB_HOST="cn", DB_PORT=11003, DB_NAME="postgres", DB_USER="admin")

        with patch("backend.tools.execute_sql_tool.Config", return_value=config), patch(
            "backend.tools.execute_sql_tool.OpenTenBaseConnector", return_value=connector
        ), patch("backend.tools.execute_sql_tool._record_execution", return_value=True) as audit:
            result = await execute_sql("SELECT secret_column FROM private_table")

        self.assertTrue(result["success"])
        self.assertEqual(result["rows"], [{"value": 1}])
        self.assertTrue(result["audit_recorded"])
        self.assertEqual(audit.call_args.args[1], "SELECT secret_column FROM private_table")
        self.assertEqual(audit.call_args.args[2], "success")
        cursor.execute.assert_called_once_with("SELECT secret_column FROM private_table")
        connection.close.assert_not_called()
        connector.close.assert_called_once()

    async def test_database_error_is_returned_and_audited(self):
        connector = MagicMock()
        connection = connector.connect.return_value
        connection.closed = 0
        connector._connection = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = RuntimeError("permission denied")
        config = SimpleNamespace(DB_HOST="cn", DB_PORT=11003, DB_NAME="postgres", DB_USER="admin")

        with patch("backend.tools.execute_sql_tool.Config", return_value=config), patch(
            "backend.tools.execute_sql_tool.OpenTenBaseConnector", return_value=connector
        ), patch("backend.tools.execute_sql_tool._record_execution", return_value=True) as audit:
            result = await execute_sql("DROP TABLE sample")

        self.assertFalse(result["success"])
        self.assertIn("permission denied", result["error"])
        self.assertEqual(audit.call_args.args[2], "failed")
        connection.rollback.assert_called_once()
