from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deployment_backup", ROOT / "deploy/backup.py")
backup_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_module)


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "source.sqlite3"
        self.destination = self.root / "backups"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE evidence (fact TEXT)")
            connection.execute("INSERT INTO evidence VALUES ('original')")

    def run_backup(self, keep: str = "14") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(ROOT / "deploy/backup.sh"), str(self.database), str(self.destination)],
            env={**os.environ, "SPORTS_BRIEFING_BACKUP_KEEP": keep},
            capture_output=True, text=True, timeout=20,
        )

    def readback(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT fact FROM evidence").fetchall(), [("original",)])

    def test_invalid_retention_does_not_create_or_modify_any_files(self) -> None:
        self.destination.mkdir()
        existing = self.destination / "sports_briefing-20260101T000000Z.sqlite3"
        existing.write_bytes(b"retained")
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        for keep in ("0", "-1", "two", "", "1.5", "10001", "999999999999999999999999", " 2"):
            with self.subTest(keep=keep):
                self.assertNotEqual(self.run_backup(keep).returncode, 0)
                after = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
                self.assertEqual(after, before)

    def test_repeat_and_concurrent_backups_have_unique_complete_files(self) -> None:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.run_backup(), range(4)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        copies = list(self.destination.glob("*.sqlite3"))
        self.assertEqual(len(copies), 4)
        self.assertFalse(list(self.destination.glob("*.partial")))
        for path in copies:
            self.readback(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_retention_protects_source_and_ignores_symlinks_and_unowned_names(self) -> None:
        self.destination = self.root
        renamed = self.root / "sports_briefing-20250101T000000Z.sqlite3"
        self.database.rename(renamed)
        self.database = renamed
        link = self.root / "sports_briefing-20250102T000000Z.sqlite3"
        link.symlink_to(self.database)
        hardlink = self.root / "sports_briefing-20250103T000000Z.sqlite3"
        os.link(self.database, hardlink)
        unrelated = self.root / "sports_briefing-not-a-backup.sqlite3"
        unrelated.write_bytes(b"leave alone")
        future = self.root / "sports_briefing-29990101T000000Z.sqlite3"
        future.write_bytes(b"old copy")
        self.assertEqual(self.run_backup("1").returncode, 0)
        self.assertFalse(future.exists())
        self.assertTrue(link.is_symlink())
        self.assertTrue(hardlink.exists())
        self.assertEqual(unrelated.read_bytes(), b"leave alone")
        self.readback(self.database)
        copies = [path for path in self.root.glob("*.sqlite3") if not path.samefile(self.database)
                  and path != unrelated]
        self.assertEqual(len(copies), 1)
        self.readback(copies[0])

    def test_failed_copy_leaves_backups_untouched_and_removes_partial(self) -> None:
        self.destination.mkdir()
        existing = self.destination / "sports_briefing-20260101T000000Z.sqlite3"
        existing.write_bytes(b"retained")
        with patch.object(backup_module.sqlite3, "connect", side_effect=sqlite3.DatabaseError("failure")):
            with self.assertRaises(sqlite3.DatabaseError):
                backup_module.backup(self.database, self.destination, "1")
        self.assertEqual(existing.read_bytes(), b"retained")
        self.assertEqual(list(self.destination.glob("*.sqlite3")), [existing])
        self.assertFalse(list(self.destination.glob("*.partial")))

    def test_quoted_and_newline_paths_restore_exact_contents_and_retention(self) -> None:
        renamed = self.root / "source 'quoted'\n.sqlite3"
        self.database.rename(renamed)
        self.database = renamed
        self.destination = self.root / "backups 'quoted'\nfolder"
        for _ in range(3):
            result = self.run_backup("2")
            self.assertEqual(result.returncode, 0, result.stderr)
        copies = list(self.destination.glob("*.sqlite3"))
        self.assertEqual(len(copies), 2)
        for path in copies:
            self.readback(path)
        restored = self.root / "restored.sqlite3"
        restored.write_bytes(copies[0].read_bytes())
        self.readback(restored)

    def test_missing_database_is_expected_and_does_not_create_state(self) -> None:
        self.database = self.root / "missing.sqlite3"
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to back up", result.stdout)
        self.assertFalse(self.database.exists())
        self.assertFalse(self.destination.exists())
