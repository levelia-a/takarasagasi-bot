import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.migrate_sqlite import read_source


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "legacy.db"
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO settings VALUES ('beginner_price', '1');
                CREATE TABLE settings_old (difficulty TEXT, price INT, success_rate INT, max_exploration INT);
                INSERT INTO settings_old VALUES ('beginner', 1000, 60, 5);
                CREATE TABLE statistics (id INT, total_plays INT);
                INSERT INTO statistics VALUES (1, 900);
                CREATE TABLE history (id INT, user_id INT, user_name TEXT, difficulty TEXT,
                    start_price INT, success_count INT, final_reward INT, result TEXT,
                    failure_point INT, created_at TEXT);
                INSERT INTO history VALUES (1, 1545489116127559681, 'テスト🌟', '初級',
                    1000, 1, 2000, 'retreat', NULL, '2026-09-20 15:00:00');
            """)

    def test_legacy_requires_explicit_test_classification(self):
        with self.assertRaisesRegex(ValueError, "テスト判定"):
            read_source(self.path)

    def test_current_settings_win_and_source_is_unchanged(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        payload, digest = read_source(self.path, "test")
        self.assertEqual(payload["settings"]["beginner_price"], 1)
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["is_test"], 1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertEqual(read_source(self.path, "test")[1], digest)

    def test_modern_history_preserves_test_flag(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript("""
                DROP TABLE statistics;
                ALTER TABLE history RENAME TO statistics;
                ALTER TABLE statistics ADD COLUMN is_test INT DEFAULT 1;
            """)
        payload, _ = read_source(self.path)
        self.assertEqual(payload["records"][0]["is_test"], 1)
