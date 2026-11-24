"""Resumable, offline-first metadata batch processor."""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from cartridges import load_cartridge

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data/publishing_queue.sqlite3"
GENERATOR = ROOT / "scripts/ai_metadata.py"
DEFAULT_JOB = ROOT / "jobs/imtp7rbbema-4a797bec"


def pending_clips(source_id):
    with sqlite3.connect(DB) as conn:
        rows = conn.execute("""
            SELECT pq.clip_number,
                   pm.platform,
                   pm.generation_status,
                   pm.review_status
            FROM publishing_queue pq
            JOIN platform_metadata pm
              ON pm.clip_path = pq.clip_path
            WHERE pq.source_id = ?
            ORDER BY pq.clip_number, pm.platform
        """, (source_id,)).fetchall()

    grouped = {}

    for number, platform, generation, review in rows:
        grouped.setdefault(number, []).append(
            (platform, generation, review)
        )

    pending = []

    for number, platforms in sorted(grouped.items()):
        if any(
            review == "pending"
            and generation not in ("complete", "needs_review")
            for _, generation, review in platforms
        ):
            pending.append(number)

    return pending, grouped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cartridge", default="gtavi")
    parser.add_argument("--job")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    cartridge = load_cartridge(args.cartridge)
    source_id = cartridge.get("source_id")

    if not source_id:
        raise SystemExit("Cartridge has no source_id")

    job = Path(args.job) if args.job else DEFAULT_JOB

    if not job.is_dir():
        job = ROOT / "jobs" / str(args.job)

    candidates = json.loads(
        (job / "candidates.json").read_text()
    )["candidates"]

    valid = {int(candidate["n"]) for candidate in candidates}

    pending, grouped = pending_clips(source_id)
    pending = [number for number in pending if number in valid]

    print("=== METADATA BATCH PROCESSOR ===", flush=True)
    print("Cartridge:", args.cartridge, flush=True)
    print("Candidates:", len(valid), flush=True)
    print("Queued clips:", len(grouped), flush=True)
    print("Clips needing generation:", len(pending), flush=True)
    print("Mode:", "RUN" if args.run else "DRY RUN", flush=True)

    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be positive")
        pending = pending[:args.limit]

    for index, number in enumerate(pending, 1):
        print(
            f"\\n[{index}/{len(pending)}] CLIP {number}",
            flush=True
        )

        if not args.run:
            print("PREVIEW: Would generate pending metadata.")
            continue

        command = [
            sys.executable,
            str(GENERATOR),
            "--cartridge", args.cartridge,
            "--clip", str(number),
            "--job", str(job),
        ]

        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
        )

        if result.returncode:
            print(
                f"FAILED: Clip {number} "
                f"(exit={result.returncode})",
                flush=True
            )

    print("\\nBATCH FINISHED.", flush=True)
    print("Nothing uploaded or published.", flush=True)


if __name__ == "__main__":
    main()
