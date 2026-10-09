"""Consistent local SQLite backups with serialized, count-based retention."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile


BACKUP_NAME = re.compile(r"sports_briefing-\d{8}T\d{6}(?:\d{6})?Z(?:-[a-z0-9_]+)?\.sqlite3\Z")
MAX_KEEP = 10000


def retention_count(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,5}", value) or not 1 <= int(value) <= MAX_KEEP:
        raise ValueError(f"SPORTS_BRIEFING_BACKUP_KEEP must be a decimal integer from 1 to {MAX_KEEP}")
    return int(value)


def backup(database: Path, destination: Path, keep_value: str) -> Path | None:
    keep = retention_count(keep_value)
    if not database.is_file():
        print(f"no database at {database}; nothing to back up")
        return None
    source = database.resolve()
    destination.mkdir(parents=True, exist_ok=True, mode=0o750)
    lock_fd = os.open(destination / ".sports_briefing-backup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o640)
    with os.fdopen(lock_fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        fd, name = tempfile.mkstemp(prefix=f".sports_briefing-{stamp}-", suffix=".partial", dir=destination)
        partial = Path(name)
        os.close(fd)
        final = destination / (partial.name[1:].removesuffix(".partial") + ".sqlite3")
        try:
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
                with closing(sqlite3.connect(partial)) as copy:
                    original.backup(copy)
                    if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise ValueError("backup integrity check failed")
            partial.chmod(0o640)
            # Linking publishes the complete file without replacing an existing backup.
            os.link(partial, final)
        finally:
            partial.unlink(missing_ok=True)
        print(f"backup written: {final}")
        eligible = []
        for path in destination.iterdir():
            if not BACKUP_NAME.fullmatch(path.name) or not stat.S_ISREG(path.lstat().st_mode):
                continue
            if path.samefile(source):
                continue
            eligible.append(path)
        # Always retain the successful new copy, even if old filenames have future timestamps.
        older = sorted((path for path in eligible if path != final), reverse=True)
        for path in older[keep - 1:]:
            path.unlink()
            print(f"removed old backup: {path}")
        return final


def main() -> int:
    try:
        database_value = sys.argv[1] if len(sys.argv) > 1 else os.environ["SPORTS_BRIEFING_DATABASE"]
        database = Path(database_value)
        destination = Path(sys.argv[2]) if len(sys.argv) > 2 else database.parent / "backups"
        backup(database, destination, os.environ.get("SPORTS_BRIEFING_BACKUP_KEEP", "14"))
    except (KeyError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
