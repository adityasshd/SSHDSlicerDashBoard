#!/usr/bin/env python3
"""Read-only backup of both Slicer databases to external local BSON archives.

Requires MongoDB Database Tools (mongodump), pymongo, and MONGO_URI in the
local environment or repository .env. Never writes to the source cluster.
Archives contain sensitive data: keep them private, encrypted and off GitHub.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

DB_NAMES = ("slicing_dashboard", "Slicer_Analytics")
ROOT = Path(__file__).resolve().parent.parent


def load_uri() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    uri = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")
    if not uri or not uri.startswith(("mongodb://", "mongodb+srv://")):
        raise RuntimeError("Set MONGO_URI or MONGODB_URI in the environment or .env")
    return uri


@contextmanager
def safe_tool_config(uri: str):
    """Keep MongoDB credentials out of the command-line process list."""
    fd, path = tempfile.mkstemp(prefix="slicer-mongodump-", suffix=".yml")
    try:
        os.fchmod(fd, 0o600) if hasattr(os, "fchmod") else None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("uri: " + json.dumps(uri) + "\n")
        yield path
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def snapshot_counts(client):
    """Source counts/index names for post-dump comparison, no source writes."""
    result = {}
    for name in DB_NAMES:
        database = client[name]
        collections = {}
        for coll_name in sorted(database.list_collection_names()):
            collection = database[coll_name]
            collections[coll_name] = {
                "documents": collection.count_documents({}),
                "indexes": sorted(idx["name"] for idx in collection.list_indexes()),
            }
        result[name] = collections
    return result


def digest_file(path: Path):
    checksum = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def within(path: Path, parent: Path):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def run(output: Path):
    if shutil.which("mongodump") is None:
        raise RuntimeError("mongodump was not found. Install MongoDB Database Tools.")
    output = output.expanduser().resolve()
    if within(output, ROOT):
        raise RuntimeError("Choose an output folder OUTSIDE the Git repository.")
    uri = load_uri()
    from pymongo import MongoClient
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output / ("slicer-" + stamp)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    files = []
    with MongoClient(uri, serverSelectionTimeoutMS=15000, appname="SlicerSafeBackup") as client:
        client.admin.command("ping")
        before = snapshot_counts(client)
        with safe_tool_config(uri) as config:
            for db_name in DB_NAMES:
                archive = destination / (db_name + ".archive.gz")
                args = ["mongodump", "--config", config, "--db", db_name,
                        "--archive=" + str(archive), "--gzip",
                        "--numParallelCollections=1"]
                # Avoid printing MongoDB connection strings or passwords.
                process = subprocess.run(args, text=True, capture_output=True, check=False)
                if process.returncode or not archive.is_file() or not archive.stat().st_size:
                    archive.unlink(missing_ok=True)
                    raise RuntimeError(f"mongodump failed for {db_name} (exit {process.returncode}). "
                                       "No database records were changed.")
                files.append({"database": db_name, "filename": archive.name,
                              "bytes": archive.stat().st_size, "sha256": digest_file(archive)})
        after = snapshot_counts(client)
    unchanged = before == after
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "method": "mongodump --db --archive --gzip (one archive per database)",
        "databases": list(DB_NAMES), "files": files,
        "before": before, "after": after, "counts_and_indexes_unchanged": unchanged,
        "restore_test_passed": False,
        "safe_to_delete_raw_records": False,
        "caveats": [
            "A live mongodump without a coordinated write pause is not a point-in-time snapshot.",
            "Verify restore into an ISOLATED database before approving any purge.",
            "Backups contain confidential data; encrypt and store off the application host.",
        ],
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Archives saved to:", destination)
    print("Collections stable during capture:", unchanged)
    print("Archive checksums written to manifest.json; RESTORE NOT YET VERIFIED")
    if not unchanged:
        print("WARNING: Source documents or indexes changed during the dump. "
              "Do not use this capture to authorize deletion.", file=sys.stderr)
    return 0 if unchanged else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Private external backup directory, outside the Git repository")
    parser.add_argument("--dry-run", action="store_true", help="Show prerequisites without connecting")
    args = parser.parse_args()
    if args.dry_run:
        print("Databases:", ", ".join(DB_NAMES))
        print("Requires mongodump, pymongo and MONGO_URI/MONGODB_URI.")
        print("Will create compressed archives and a count/checksum manifest.")
        print("No database writes or deletions; restore verification remains required.")
        return 0
    try:
        return run(args.output)
    except Exception as exc:
        # Driver/tool errors can contain connection strings or other secrets.
        print("Backup did not complete:", type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
