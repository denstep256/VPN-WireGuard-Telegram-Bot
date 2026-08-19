import sqlite3
import unittest

from app.database.migrate_db_old import migrate_test_period


class LegacyMigrationTests(unittest.TestCase):
    def test_only_one_trial_is_migrated_per_user(self):
        old_connection = sqlite3.connect(":memory:")
        new_connection = sqlite3.connect(":memory:")
        self.addCleanup(old_connection.close)
        self.addCleanup(new_connection.close)

        old_connection.execute(
            """
            CREATE TABLE test_period (
                tg_id INTEGER,
                username TEXT,
                file_name TEXT,
                subscription TEXT,
                expiry_date TEXT,
                notif_oneday INTEGER
            )
            """
        )
        new_connection.execute(
            """
            CREATE TABLE test_period (
                id INTEGER PRIMARY KEY,
                tg_id INTEGER UNIQUE,
                username TEXT,
                file_name TEXT,
                subscription TEXT,
                expiry_date TEXT,
                notif_oneday INTEGER
            )
            """
        )
        old_connection.executemany(
            "INSERT INTO test_period VALUES (?, ?, ?, ?, ?, ?)",
            (
                (101, "user", "client-one", "trial", "2026-08-20", 0),
                (101, "user", "client-two", "trial_used", "2026-08-21", 1),
            ),
        )

        stats = migrate_test_period(old_connection, new_connection)

        self.assertEqual(stats.inserted, 1)
        self.assertEqual(stats.skipped_duplicates, 1)
        self.assertEqual(
            new_connection.execute("SELECT COUNT(*) FROM test_period").fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
