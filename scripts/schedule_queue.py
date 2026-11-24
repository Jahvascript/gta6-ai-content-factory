"""Offline-first scheduling queue. No platform uploads."""

import argparse
import sqlite3
from datetime import datetime, timezone

from schedule_planner import plan
from publishing_eligibility import DB, audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    if not 1 <= args.days <= 365:
        parser.error("--days must be between 1 and 365")

    candidates = plan(days=args.days)

    print("=== AUTOMATIC SCHEDULING QUEUE ===")
    print("Mode:", "COMMIT" if args.commit else "PREVIEW")
    print("Eligible candidates:", len(candidates))

    if not args.commit:
        for item in candidates[:15]:
            print(
                item["platform"],
                item["local_time"],
                item["clip_path"]
            )
        print("No database changes.")
        return

    # Recheck eligibility immediately before writing.
    eligible = {
        (item["clip_path"], item["platform"])
        for item in audit()
        if item["eligible"]
    }

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0

    conn = sqlite3.connect(DB)

    try:
        conn.execute("BEGIN IMMEDIATE")

        for item in candidates:
            key = (item["clip_path"], item["platform"])

            if key not in eligible:
                continue

            # Never create multiple active schedules for one
            # clip/platform combination.
            exists = conn.execute("""
                SELECT 1
                FROM publishing_schedule
                WHERE clip_path = ?
                  AND platform = ?
                  AND status != 'cancelled'
                LIMIT 1
            """, key).fetchone()

            if exists:
                continue

            conn.execute("""
                INSERT INTO publishing_schedule (
                    clip_path,
                    platform,
                    scheduled_at,
                    timezone,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 'draft', ?, ?)
            """, (
                item["clip_path"],
                item["platform"],
                item["scheduled_at"],
                "UTC",
                now,
                now
            ))

            inserted += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("Draft schedule records created:", inserted)
    print("No uploads, external scheduling, or publishing.")


if __name__ == "__main__":
    main()
