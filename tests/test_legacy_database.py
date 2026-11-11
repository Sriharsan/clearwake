"""A database made before the 12 Nov 2026 rename is kept aside and the console starts fresh."""
import tempfile
import unittest
from pathlib import Path

from clearwake.controller import RefundController, archive_legacy_database


class LegacyDatabaseTests(unittest.TestCase):
    def test_an_old_database_is_kept_aside_and_a_new_one_opens(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            old, provider = base / "clearwake.sqlite3", base / "rehearsal-provider.sqlite3"
            old.write_bytes(b"old"); provider.write_bytes(b"old provider")
            moved = archive_legacy_database(old)
            self.assertEqual(len(moved), 2)
            self.assertFalse(old.exists() or provider.exists())
            self.assertTrue(all((base / name).exists() for name in moved))
            controller = RefundController(old)   # a fresh database opens under the new names
            controller.close()

    def test_a_current_database_is_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "clearwake.sqlite3"
            database.write_bytes(b"current")
            self.assertEqual(archive_legacy_database(database), [])
            self.assertTrue(database.exists())


if __name__ == "__main__":
    unittest.main()
