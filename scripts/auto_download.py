"""Automatically download new CC-labeled GTA VI videos."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "jobs/cc_candidates.json"
ARCHIVE = ROOT / "data/downloaded_ids.txt"
INCOMING = ROOT / "footage/incoming"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--min-minutes", type=float, default=2)
    ap.add_argument("--max-minutes", type=float, default=30)
    args = ap.parse_args()

    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    INCOMING.mkdir(parents=True, exist_ok=True)
    ARCHIVE.touch(exist_ok=True)

    if not CANDIDATES.exists():
        raise SystemExit("Run cc_discovery.py first.")

    candidates = json.loads(CANDIDATES.read_text())

    downloaded = set()
    for line in ARCHIVE.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            downloaded.add(parts[-1])

    successes = 0

    for item in candidates:
        if successes >= args.limit:
            break

        if not item.get("reported_cc"):
            continue

        url = item.get("url", "")
        video_id = url.split("v=")[-1].split("&")[0]

        if not video_id or video_id in downloaded:
            continue

        print(f"\nChecking: {video_id}", flush=True)

        probe = subprocess.run(
            ["yt-dlp", "--skip-download", "--dump-single-json",
             "--no-playlist", url],
            capture_output=True, text=True
        )

        if probe.returncode:
            print("Metadata unavailable. Skipping.", flush=True)
            continue

        try:
            info = json.loads(probe.stdout)
        except json.JSONDecodeError:
            continue

        duration = info.get("duration")
        live_status = info.get("live_status", "")

        if live_status in ("is_live", "is_upcoming", "post_live"):
            print("Skipping livestream.", flush=True)
            continue

        if not duration:
            print("Skipping unknown duration.", flush=True)
            continue

        minutes = duration / 60

        if not args.min_minutes <= minutes <= args.max_minutes:
            print(f"Skipping duration: {minutes:.1f} minutes", flush=True)
            continue

        license_text = (info.get("license") or "").lower()
        if "creative commons" not in license_text:
            print("CC license no longer reported. Skipping.", flush=True)
            continue

        print(f"Downloading: {minutes:.1f} min | {info.get('title')}", flush=True)

        command = [
            "yt-dlp",
            "--no-playlist",
            "--download-archive", str(ARCHIVE),
            "--write-info-json",
            "--write-description",
            "--embed-metadata",
            "--merge-output-format", "mp4",
            "-f", "bv*[height<=720]+ba/b[height<=720]/best",
            "-o", str(INCOMING / "%(id)s.%(ext)s"),
            url
        ]

        result = subprocess.run(command)

        if result.returncode == 0:
            successes += 1
            downloaded.add(video_id)
            print("DOWNLOAD SUCCESSFUL", flush=True)
        else:
            print("Download failed. Trying next candidate.", flush=True)

    print(f"\nCompleted: {successes} new downloads.")

if __name__ == "__main__":
    main()
