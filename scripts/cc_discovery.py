"""Discover GTA VI Creative Commons candidates without downloading footage."""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

def ytdlp(*args):
    p = subprocess.run(
        ["yt-dlp", "--no-warnings", "--no-playlist", "-J", *args],
        capture_output=True, text=True
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[-500:])
    return json.loads(p.stdout)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="GTA VI gameplay")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--out", default="cc_candidates.md")
    args = parser.parse_args()

    # YouTube Creative Commons search filter.
    search = (
        "https://www.youtube.com/results?search_query="
        + quote_plus(args.query)
        + "&sp=EgIwAQ%253D%253D"
    )

    print("Searching YouTube for Creative Commons candidates...", flush=True)
    p = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--dump-single-json",
         "--playlist-end", str(args.limit), search],
        capture_output=True, text=True
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip()[-500:])

    entries = json.loads(p.stdout).get("entries") or []
    rows = []

    for entry in entries:
        if not entry or not entry.get("id"):
            continue

        url = "https://www.youtube.com/watch?v=" + entry["id"]

        try:
            info = ytdlp(url)
        except Exception as exc:
            print("Skipped:", url, str(exc)[:100])
            continue

        license_text = info.get("license") or "Not reported"
        is_cc = "creative commons" in license_text.lower()

        rows.append({
            "title": info.get("title") or "",
            "channel": info.get("channel") or "",
            "url": url,
            "license": license_text,
            "duration": info.get("duration"),
            "views": info.get("view_count"),
            "reported_cc": is_cc,
            "clearance": "UNVERIFIED",
        })

        print(("CC candidate" if is_cc else "Unverified"),
              "-", info.get("title", "")[:65], flush=True)

    Path("jobs").mkdir(exist_ok=True)
    Path("jobs/cc_candidates.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )

    lines = [
        "# GTA VI — Creative Commons Discovery",
        "",
        "Generated: " + datetime.now(timezone.utc).isoformat(),
        "",
        "All candidates require rights verification before reuse.",
        "",
        "| Title | Channel | Reported license | Clearance | Source |",
        "|---|---|---|---|---|",
    ]

    for r in rows:
        title = r["title"].replace("|", "/").replace("\n", " ")
        channel = r["channel"].replace("|", "/").replace("\n", " ")
        license_text = r["license"].replace("|", "/")
        lines.append(
            f"| {title[:65]} | {channel[:30]} | {license_text} "
            f"| {r['clearance']} | [Video]({r['url']}) |"
        )

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nFound {len(rows)} candidates -> {args.out}")
    print("No videos downloaded. Clearance remains unverified.")

if __name__ == "__main__":
    main()
