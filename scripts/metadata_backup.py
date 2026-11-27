#!/usr/bin/env python3
"""Back up, verify, or restore the AIOps metadata PostgreSQL database."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_USER = "aiops_knowledge"
DATABASE_NAME = os.getenv("KNOWLEDGE_DB_NAME", "aiops_knowledge")
CORE_TABLES = ("knowledge_documents", "knowledge_chunks", "audit_records")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as archive:
        for block in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_database_name(database):
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,62}", database):
        raise ValueError("Target database must be a simple PostgreSQL identifier")
    if database == DATABASE_NAME or database in {"postgres", "template0", "template1"}:
        raise ValueError("Restore target must be a new database, not a configured or system database")


def _docker_exec(*arguments, stdin=None, stdout=None, capture_output=False, text=False):
    if capture_output and stdout is None:
        stdout = subprocess.PIPE
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "knowledge-db", *arguments],
        cwd=ROOT,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.PIPE if capture_output else None,
        text=text,
        check=True,
    )


def _psql(database, statement):
    result = _docker_exec(
        "psql", "-U", DATABASE_USER, "-d", database, "-v", "ON_ERROR_STOP=1",
        "-A", "-t", "-c", statement, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _verify_checksum(archive_path):
    checksum_path = Path(f"{archive_path}.sha256")
    if not checksum_path.is_file():
        raise ValueError(f"Checksum file is missing: {checksum_path}")
    expected = checksum_path.read_text(encoding="ascii").split()[0]
    actual = sha256_file(archive_path)
    if expected != actual:
        raise ValueError("Backup checksum does not match the archive")
    return actual


def _restore_archive(archive_path, database):
    with open(archive_path, "rb") as archive:
        _docker_exec(
            "pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
            "-U", DATABASE_USER, "-d", database, stdin=archive,
        )


def _validate_core_tables(database):
    core_tables_sql = ", ".join(f"'{name}'" for name in CORE_TABLES)
    existing_tables = set(filter(None, _psql(
        database,
        "SELECT tablename FROM pg_catalog.pg_tables "
        f"WHERE schemaname='public' AND tablename IN ({core_tables_sql}) ORDER BY tablename",
    ).splitlines()))
    missing = sorted(set(CORE_TABLES) - existing_tables)
    if missing:
        raise RuntimeError(f"Restored database is missing core tables: {', '.join(missing)}")

    counts = {}
    for table in CORE_TABLES:
        counts[table] = int(_psql(database, f"SELECT count(*) FROM public.{table}"))
    return counts


def backup(output_directory):
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = output_directory / f"aiops-metadata-{timestamp}.dump"
    temporary_path = archive_path.with_suffix(".dump.partial")
    checksum_path = Path(f"{archive_path}.sha256")
    checksum_temporary = Path(f"{checksum_path}.partial")

    try:
        with open(temporary_path, "wb") as archive:
            _docker_exec(
                "pg_dump", "-U", DATABASE_USER, "-d", DATABASE_NAME,
                "--format=custom", "--no-owner", "--no-acl", stdout=archive,
            )
            archive.flush()
            os.fsync(archive.fileno())
        digest = sha256_file(temporary_path)
        os.replace(temporary_path, archive_path)
        checksum_temporary.write_text(
            f"{digest}  {archive_path.name}\n", encoding="ascii"
        )
        os.replace(checksum_temporary, checksum_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        checksum_temporary.unlink(missing_ok=True)
        archive_path.unlink(missing_ok=True)
        raise

    return {"archive": str(archive_path), "sha256": digest}


def verify(archive_path):
    archive_path = archive_path.resolve()
    digest = _verify_checksum(archive_path)
    with open(archive_path, "rb") as archive:
        toc = _docker_exec(
            "pg_restore", "--list", stdin=archive,
            capture_output=True, text=True,
        ).stdout
    toc_entries = sum(
        1 for line in toc.splitlines() if line.strip() and not line.lstrip().startswith(";")
    )
    if not toc_entries:
        raise RuntimeError("Backup archive contains no restore entries")

    database = f"aiops_restore_verify_{uuid.uuid4().hex[:16]}"
    created = False
    try:
        _psql("postgres", f"CREATE DATABASE {database}")
        created = True
        _restore_archive(archive_path, database)
        counts = _validate_core_tables(database)
    finally:
        if created:
            _psql("postgres", f"DROP DATABASE IF EXISTS {database}")

    return {
        "archive": str(archive_path),
        "sha256": digest,
        "restore_entries": toc_entries,
        "verified_core_row_counts": counts,
        "temporary_database_removed": True,
    }


def restore(archive_path, database):
    validate_database_name(database)
    archive_path = archive_path.resolve()
    digest = _verify_checksum(archive_path)
    exists = _psql(
        "postgres",
        "SELECT 1 FROM pg_catalog.pg_database WHERE datname='" + database + "'",
    )
    if exists:
        raise ValueError(f"Restore target database already exists: {database}")

    created = False
    try:
        _psql("postgres", f"CREATE DATABASE {database}")
        created = True
        _restore_archive(archive_path, database)
        counts = _validate_core_tables(database)
    except Exception:
        if created:
            _psql("postgres", f"DROP DATABASE IF EXISTS {database}")
        raise

    return {"database": database, "sha256": digest, "verified_core_row_counts": counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup", help="create a custom-format backup")
    backup_parser.add_argument("--output-directory", type=Path, default=ROOT / "backups")
    verify_parser = commands.add_parser("verify", help="restore into a temporary database and validate")
    verify_parser.add_argument("archive", type=Path)
    restore_parser = commands.add_parser("restore", help="restore into a new, empty database name")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("--database", required=True)
    arguments = parser.parse_args()

    try:
        if arguments.command == "backup":
            result = backup(arguments.output_directory.resolve())
        elif arguments.command == "verify":
            result = verify(arguments.archive)
        else:
            result = restore(arguments.archive, arguments.database)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
