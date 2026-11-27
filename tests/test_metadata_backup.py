import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.metadata_backup import _verify_checksum, main, validate_database_name


class MetadataBackupTests(unittest.TestCase):
    def test_checksum_detects_modified_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "backup.dump"
            archive.write_bytes(b"archive-content")
            Path(f"{archive}.sha256").write_text(
                f"{hashlib.sha256(b'archive-content').hexdigest()}  backup.dump\n",
                encoding="ascii",
            )

            self.assertEqual(
                _verify_checksum(archive), hashlib.sha256(b"archive-content").hexdigest()
            )

            archive.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                _verify_checksum(archive)

    def test_restore_rejects_configured_and_system_databases(self):
        for database in ("aiops_knowledge", "postgres", "template0", "template1"):
            with self.subTest(database=database):
                with self.assertRaisesRegex(ValueError, "new database"):
                    validate_database_name(database)

    def test_restore_requires_simple_database_identifier(self):
        for database in ("starts-with-digit", "has space", "quoted\"name", "a" * 64):
            with self.subTest(database=database):
                with self.assertRaisesRegex(ValueError, "identifier"):
                    validate_database_name(database)

    def test_restore_accepts_new_simple_database_name(self):
        with patch("scripts.metadata_backup.DATABASE_NAME", "configured_metadata"):
            validate_database_name("aiops_recovery_01")

    def test_cli_reports_refused_restore_target_without_traceback(self):
        with patch("sys.argv", [
            "metadata_backup.py", "restore", "backup.dump", "--database", "aiops_knowledge"
        ]):
            with self.assertRaises(SystemExit) as exit_error:
                main()

        self.assertEqual(exit_error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
