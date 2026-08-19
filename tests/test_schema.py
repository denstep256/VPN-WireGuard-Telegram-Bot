import unittest

from sqlalchemy import create_engine

from app.database.models import _apply_sqlite_compatibility_migrations


class SchemaMigrationTests(unittest.TestCase):
    def test_legacy_sqlite_schema_gets_columns_and_unique_indexes(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE test_period (id INTEGER PRIMARY KEY, tg_id BIGINT)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE payments (id INTEGER PRIMARY KEY, provider_payment_charge_id VARCHAR)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE servers (id INTEGER PRIMARY KEY, region VARCHAR, region_id INTEGER)"
            )

            _apply_sqlite_compatibility_migrations(connection)
            _apply_sqlite_compatibility_migrations(connection)

            columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(test_period)"
                ).fetchall()
            }
            self.assertIn("server_region", columns)
            self.assertIn("server_region_id", columns)

            index_names = {
                row[1]
                for table in ("test_period", "payments", "servers")
                for row in connection.exec_driver_sql(
                    f"PRAGMA index_list({table})"
                ).fetchall()
            }
            self.assertIn("uq_test_period_tg_id_idx", index_names)
            self.assertIn("uq_payment_provider_charge_idx", index_names)
            self.assertIn("uq_server_region_id_idx", index_names)


if __name__ == "__main__":
    unittest.main()
