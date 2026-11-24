"""Offline-first publishing schedule planner. Preview only."""

import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from publishing_eligibility import audit, DB

LOCAL_ZONE = ZoneInfo("America/New_York")

SLOTS = {
    "youtube": (9, 13, 19),
    "instagram": (9, 13, 19),
    "tiktok": (9, 13, 19),
}


def existing_schedule():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return {
            (clip_path, platform)
            for clip_path, platform in conn.execute("""
                SELECT clip_path, platform
                FROM publishing_schedule
                WHERE status != 'cancelled'
            """)
        }
    finally:
        conn.close()


def plan(start_date=None, days=14):
    now = datetime.now(LOCAL_ZONE)
    first_day = start_date or (now.date() + timedelta(days=1))

    eligible = [
        item for item in audit()
        if item["eligible"]
    ]

    already = existing_schedule()

    by_platform = {
        platform: sorted(
            (
                item for item in eligible
                if item["platform"] == platform
                and (item["clip_path"], platform) not in already
            ),
            key=lambda item: item["clip_path"]
        )
        for platform in SLOTS
    }

    results = []

    for platform, items in by_platform.items():
        position = 0

        for day_offset in range(days):
            day = first_day + timedelta(days=day_offset)

            for hour in SLOTS[platform]:
                if position >= len(items):
                    break

                local_time = datetime(
                    day.year, day.month, day.day,
                    hour, 0, tzinfo=LOCAL_ZONE
                )

                results.append({
                    "clip_path": items[position]["clip_path"],
                    "platform": platform,
                    "local_time": local_time.isoformat(),
                    "scheduled_at": local_time.astimezone(
                        timezone.utc
                    ).isoformat(),
                })

                position += 1

    return sorted(
        results,
        key=lambda item: (
            item["scheduled_at"],
            item["platform"]
        )
    )


if __name__ == "__main__":
    print("=== OFFLINE SCHEDULING PREVIEW ===")

    results = plan()

    print("Eligible scheduling entries:", len(results))

    for item in results[:15]:
        print(
            item["platform"],
            Path(item["clip_path"]).name,
            item["local_time"],
            "UTC:", item["scheduled_at"]
        )

    if len(results) > 15:
        print(f"... {len(results) - 15} more")

    if not results:
        print(
            "No eligible entries yet. "
            "Rights, metadata review, and publishing "
            "authorization gates remain active."
        )

    print("No schedule records created.")
    print("No uploads or publishing.")
