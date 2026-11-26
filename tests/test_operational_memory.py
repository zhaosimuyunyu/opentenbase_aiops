import unittest
from unittest.mock import MagicMock, patch

from backend.utils.operational_memory import OperationalMemory


class OperationalMemoryTests(unittest.TestCase):
    @patch("backend.utils.operational_memory.OperationsStore")
    def test_recall_uses_mapping_rows_and_parameterized_filters(self, store_type):
        store = store_type.return_value
        cursor = store.conn.cursor.return_value.__enter__.return_value
        expected = [{"case_id": "case-1", "effectiveness": 1.0}]
        cursor.fetchall.return_value = expected

        memory = OperationalMemory.__new__(OperationalMemory)
        memory.store = store

        rows = memory.recall(category="lock", query="prepared transaction", limit=1000)

        self.assertEqual(rows, expected)
        self.assertEqual(cursor.execute.call_args.args[1], (
            "lock", "%prepared transaction%", "%prepared transaction%",
            "%prepared transaction%", 50,
        ))
        store.conn.cursor.assert_called_once()
        self.assertIsNotNone(store.conn.cursor.call_args.kwargs.get("cursor_factory"))


if __name__ == "__main__":
    unittest.main()
