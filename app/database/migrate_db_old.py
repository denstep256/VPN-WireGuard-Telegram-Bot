#!/usr/bin/env python3
"""Migrate data from legacy SQLite DB (db_OLD.sqlite3) into current project DB."""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TableStats:
    inserted: int = 0
    skipped_duplicates: int = 0
    skipped_invalid: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate users/payments/subscribers/test_period from legacy DB "
            "to current DB schema."
        )
    )
    parser.add_argument(
        "--old-db",
        required=True,
        help="Path to legacy database file (db_OLD.sqlite3).",
    )
    parser.add_argument(
        "--new-db",
        default="db.sqlite3",
        help="Path to current database file (default: db.sqlite3).",
    )
    parser.add_argument(
        "--legacy-region",
        default="LEGACY",
        help=(
            "Value for subscribers.server_region when migrating old subscribers "
            "(default: LEGACY)."
        ),
    )
    parser.add_argument(
        "--legacy-region-id",
        type=int,
        default=0,
        help=(
            "Value for subscribers.server_region_id when migrating old subscribers "
            "(default: 0)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run migration and print stats without committing changes.",
    )
    return parser.parse_args()


def normalize_text(value: object | None, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def ensure_columns(
    conn: sqlite3.Connection,
    table_name: str,
    required_columns: set[str],
    db_label: str,
) -> None:
    cols = table_columns(conn, table_name)
    if not cols:
        raise RuntimeError(f"Table '{table_name}' not found in {db_label} database.")
    missing = required_columns - cols
    if missing:
        missing_sorted = ", ".join(sorted(missing))
        raise RuntimeError(
            f"Table '{table_name}' in {db_label} DB misses columns: {missing_sorted}"
        )


def migrate_users(old_conn: sqlite3.Connection, new_conn: sqlite3.Connection) -> TableStats:
    stats = TableStats()
    existing_tg = {
        row[0]
        for row in new_conn.execute("SELECT tg_id FROM users WHERE tg_id IS NOT NULL").fetchall()
    }
    rows = old_conn.execute(
        "SELECT tg_id, username, first_name, date_add FROM users"
    ).fetchall()

    for tg_id, username, first_name, date_add in rows:
        if tg_id is None:
            stats.skipped_invalid += 1
            continue
        if tg_id in existing_tg:
            stats.skipped_duplicates += 1
            continue

        new_conn.execute(
            """
            INSERT INTO users (tg_id, username, first_name, bonus_balance, date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                normalize_text(username, "unknown"),
                normalize_text(first_name, "unknown"),
                0,
                normalize_text(date_add, ""),
            ),
        )
        existing_tg.add(tg_id)
        stats.inserted += 1

    return stats


def migrate_payments(old_conn: sqlite3.Connection, new_conn: sqlite3.Connection) -> TableStats:
    stats = TableStats()

    existing_charge_ids = {
        normalize_text(row[0])
        for row in new_conn.execute(
            "SELECT provider_payment_charge_id FROM payments WHERE provider_payment_charge_id IS NOT NULL"
        ).fetchall()
        if normalize_text(row[0])
    }
    existing_fingerprints = {
        (
            row[0],
            normalize_text(row[1], "unknown"),
            row[2],
            normalize_text(row[3]),
            normalize_text(row[4]),
            normalize_text(row[5]),
        )
        for row in new_conn.execute(
            """
            SELECT tg_id, username, price, date, tarific_plan, provider_payment_charge_id
            FROM payments
            """
        ).fetchall()
    }

    rows = old_conn.execute(
        """
        SELECT tg_id, username, summa, time_to_add, payload, provider_payment_charge_id
        FROM payments
        """
    ).fetchall()

    for tg_id, username, summa, time_to_add, payload, charge_id in rows:
        charge_id_norm = normalize_text(charge_id)
        fingerprint = (
            tg_id,
            normalize_text(username, "unknown"),
            summa,
            normalize_text(time_to_add),
            normalize_text(payload),
            charge_id_norm,
        )

        if charge_id_norm and charge_id_norm in existing_charge_ids:
            stats.skipped_duplicates += 1
            continue
        if fingerprint in existing_fingerprints:
            stats.skipped_duplicates += 1
            continue
        if tg_id is None or summa is None:
            stats.skipped_invalid += 1
            continue

        new_conn.execute(
            """
            INSERT INTO payments (tg_id, username, price, date, tarific_plan, provider_payment_charge_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                normalize_text(username, "unknown"),
                int(summa),
                normalize_text(time_to_add, ""),
                normalize_text(payload, "unknown_plan"),
                charge_id_norm,
            ),
        )
        if charge_id_norm:
            existing_charge_ids.add(charge_id_norm)
        existing_fingerprints.add(fingerprint)
        stats.inserted += 1

    return stats


def migrate_subscribers(
    old_conn: sqlite3.Connection,
    new_conn: sqlite3.Connection,
    legacy_region: str,
    legacy_region_id: int,
) -> TableStats:
    stats = TableStats()

    existing_keys = {
        (
            row[0],
            normalize_text(row[1]),
            normalize_text(row[2]),
            normalize_text(row[3]),
        )
        for row in new_conn.execute(
            "SELECT tg_id, file_name, subscription, expiry_date FROM subscribers"
        ).fetchall()
    }

    rows = old_conn.execute(
        """
        SELECT tg_id, username, file_name, subscription, expiry_date, notif_oneday, note
        FROM subscribers
        """
    ).fetchall()

    for tg_id, username, file_name, subscription, expiry_date, notif_oneday, note in rows:
        if tg_id is None:
            stats.skipped_invalid += 1
            continue

        key = (
            tg_id,
            normalize_text(file_name),
            normalize_text(subscription),
            normalize_text(expiry_date),
        )
        if key in existing_keys:
            stats.skipped_duplicates += 1
            continue

        new_conn.execute(
            """
            INSERT INTO subscribers (
                tg_id, username, file_name, subscription, expiry_date,
                server_region, server_region_id, notif_oneday, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                normalize_text(username, "unknown"),
                normalize_text(file_name, "unknown"),
                normalize_text(subscription, "unknown_plan"),
                normalize_text(expiry_date, ""),
                legacy_region,
                legacy_region_id,
                1 if bool(notif_oneday) else 0,
                normalize_text(note, ""),
            ),
        )
        existing_keys.add(key)
        stats.inserted += 1

    return stats


def migrate_test_period(
    old_conn: sqlite3.Connection,
    new_conn: sqlite3.Connection,
    legacy_region: str,
    legacy_region_id: int,
) -> TableStats:
    stats = TableStats()
    existing_tg_ids = {
        row[0]
        for row in new_conn.execute(
            "SELECT tg_id FROM test_period WHERE tg_id IS NOT NULL"
        ).fetchall()
    }
    rows = old_conn.execute(
        "SELECT tg_id, username, file_name, subscription, expiry_date, notif_oneday FROM test_period"
    ).fetchall()

    for tg_id, username, file_name, subscription, expiry_date, notif_oneday in rows:
        if tg_id is None:
            stats.skipped_invalid += 1
            continue
        if tg_id in existing_tg_ids:
            stats.skipped_duplicates += 1
            continue

        new_conn.execute(
            """
            INSERT INTO test_period (
                tg_id, username, file_name, subscription, expiry_date, notif_oneday,
                server_region, server_region_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_id,
                normalize_text(username, "unknown"),
                normalize_text(file_name, "unknown"),
                normalize_text(subscription, "trial"),
                normalize_text(expiry_date, ""),
                1 if bool(notif_oneday) else 0,
                legacy_region,
                legacy_region_id,
            ),
        )
        existing_tg_ids.add(tg_id)
        stats.inserted += 1

    return stats


def print_stats(table_name: str, stats: TableStats) -> None:
    print(
        f"{table_name}: inserted={stats.inserted}, "
        f"skipped_duplicates={stats.skipped_duplicates}, "
        f"skipped_invalid={stats.skipped_invalid}"
    )


def main() -> int:
    args = parse_args()
    old_db_path = Path(args.old_db).expanduser().resolve()
    new_db_path = Path(args.new_db).expanduser().resolve()

    if not old_db_path.exists():
        print(f"[ERROR] Legacy DB not found: {old_db_path}")
        return 1
    if not new_db_path.exists():
        print(f"[ERROR] Target DB not found: {new_db_path}")
        return 1

    old_conn = sqlite3.connect(old_db_path)
    new_conn = sqlite3.connect(new_db_path)
    try:
        old_conn.row_factory = sqlite3.Row
        new_conn.row_factory = sqlite3.Row

        # Validate old schema
        ensure_columns(old_conn, "users", {"tg_id", "username", "first_name", "date_add"}, "old")
        ensure_columns(
            old_conn,
            "payments",
            {"tg_id", "username", "summa", "time_to_add", "payload", "provider_payment_charge_id"},
            "old",
        )
        ensure_columns(
            old_conn,
            "subscribers",
            {"tg_id", "username", "file_name", "subscription", "expiry_date", "notif_oneday", "note"},
            "old",
        )
        ensure_columns(
            old_conn,
            "test_period",
            {"tg_id", "username", "file_name", "subscription", "expiry_date", "notif_oneday"},
            "old",
        )

        # Validate new schema
        ensure_columns(new_conn, "users", {"tg_id", "username", "first_name", "bonus_balance", "date"}, "new")
        ensure_columns(
            new_conn,
            "payments",
            {"tg_id", "username", "price", "date", "tarific_plan", "provider_payment_charge_id"},
            "new",
        )
        ensure_columns(
            new_conn,
            "subscribers",
            {
                "tg_id",
                "username",
                "file_name",
                "subscription",
                "expiry_date",
                "server_region",
                "server_region_id",
                "notif_oneday",
                "note",
            },
            "new",
        )
        ensure_columns(
            new_conn,
            "test_period",
            {
                "tg_id",
                "username",
                "file_name",
                "subscription",
                "expiry_date",
                "notif_oneday",
                "server_region",
                "server_region_id",
            },
            "new",
        )

        new_conn.execute("BEGIN")
        users_stats = migrate_users(old_conn, new_conn)
        payments_stats = migrate_payments(old_conn, new_conn)
        subscribers_stats = migrate_subscribers(
            old_conn,
            new_conn,
            legacy_region=args.legacy_region,
            legacy_region_id=args.legacy_region_id,
        )
        test_period_stats = migrate_test_period(
            old_conn,
            new_conn,
            legacy_region=args.legacy_region,
            legacy_region_id=args.legacy_region_id,
        )

        if args.dry_run:
            new_conn.rollback()
            print("[DRY-RUN] Changes rolled back.")
        else:
            new_conn.commit()
            print("[OK] Migration committed.")

        print(f"old_db={old_db_path}")
        print(f"new_db={new_db_path}")
        print(f"legacy_region={args.legacy_region}")
        print(f"legacy_region_id={args.legacy_region_id}")
        print_stats("users", users_stats)
        print_stats("payments", payments_stats)
        print_stats("subscribers", subscribers_stats)
        print_stats("test_period", test_period_stats)
        return 0
    except Exception as exc:
        new_conn.rollback()
        print(f"[ERROR] Migration failed: {exc}")
        return 1
    finally:
        old_conn.close()
        new_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
