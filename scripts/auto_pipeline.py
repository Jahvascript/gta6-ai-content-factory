"""GTA VI automatic discovery-to-export pipeline."""
import argparse
import json
import os
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
HISTORY = ROOT / "data/pipeline_history.json"
INCOMING = ROOT / "footage/incoming"
JOBS = ROOT / "jobs"
FFMPEG = ROOT / "tools/ffmpeg"

def run(command):
    print("\n$ " + " ".join(map(str, command)), flush=True)
    env = os.environ.copy()
    env["PATH"] = str(FFMPEG) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode:
        raise RuntimeError(f"Command failed: {result.returncode}")

def load_history():
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return {}

def save_history(history):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    temp = HISTORY.with_suffix(".tmp")
    temp.write_text(json.dumps(history, indent=2))
    temp.replace(HISTORY)

def find_job(video, previous):
    """Find the analysis belonging to this exact source video."""
    source = str(video.resolve())

    matches = []
    for job in JOBS.iterdir():
        if not job.is_dir():
            continue

        path = job / "candidates.json"
        if not path.exists():
            continue

        try:
            data = json.loads(path.read_text())
            if str(Path(data["source"]).resolve()) == source:
                matches.append(job)
        except (ValueError, KeyError, OSError):
            continue

    if not matches:
        raise RuntimeError("No analysis job found for this video")

    # Prefer analysis covering the largest portion of the source.
    # This prevents an older five-minute test from replacing a full run.
    return max(
        matches,
        key=lambda job: (
            len(json.loads((job / "transcript.json").read_text()))
            if (job / "transcript.json").exists() else 0,
            (job / "candidates.json").stat().st_mtime
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads", type=int, default=1)
    parser.add_argument("--clips", type=int, default=0)
    parser.add_argument("--discover-limit", type=int, default=15)
    parser.add_argument("--skip-discovery", action="store_true")
    parser.add_argument("--skip-downloads", action="store_true")
    parser.add_argument("--min-score", type=float, default=1.5)
    parser.add_argument("--video", type=str, help="Process one source MP4 only")
    parser.add_argument("--job", type=str, help="Use an existing analysis job")
    args = parser.parse_args()

    if args.downloads < 1 or args.clips < 0:
        parser.error("downloads must be at least 1 and clips cannot be negative")

    print("=== GTA VI AI CONTENT FACTORY ===", flush=True)

    if not args.skip_discovery:
        run([
            PYTHON, "scripts/cc_discovery.py",
            "--limit", str(args.discover_limit)
        ])

    if not args.skip_downloads:
        run([
            PYTHON, "scripts/auto_download.py",
            "--limit", str(args.downloads)
        ])

    history = load_history()
    videos = sorted(INCOMING.glob("*.mp4"))

    if args.video:
        selected = Path(args.video).resolve()
        if not selected.is_file() or selected.suffix.lower() != ".mp4":
            parser.error("--video must point to an existing MP4")
        videos = [selected]

    if args.job and not args.video:
        parser.error("--job requires --video")

    for video in videos:
        video_id = video.stem
        record = history.get(video_id, {})

        if record.get("status") == "complete":
            print(
                f"Rechecking completed source for missing clips: {video_id}",
                flush=True
            )

        print(f"\n=== PROCESSING {video.name} ===", flush=True)

        try:
            if args.job:
                job = Path(args.job).resolve()
                manifest = job / "candidates.json"
                if not manifest.is_file():
                    raise RuntimeError("Selected job has no candidates.json")
                metadata = json.loads(manifest.read_text())
                if Path(metadata["source"]).resolve() != video.resolve():
                    raise RuntimeError("Job does not match selected video")
            else:
                job = find_job(video, record.get("job"))

            record["job"] = str(job)
        except RuntimeError:
            if args.job:
                raise
            run([PYTHON, "scripts/moments.py", str(video)])

            job = find_job(video, None)
            record["job"] = str(job)

        history[video_id] = record
        save_history(history)

        try:
            data = json.loads((job / "candidates.json").read_text())
            eligible = [
                candidate for candidate in data["candidates"]
                if candidate["score"] >= args.min_score
            ]
            if args.clips:
                eligible = sorted(
                    eligible, key=lambda candidate: candidate["score"], reverse=True
                )[:args.clips]

            print(f"Rendering {len(eligible)} qualifying candidates", flush=True)

            for candidate in eligible:
                number = candidate["n"]
                output = job / "edits" / f"clip_{number}.mp4"

                if output.exists() and output.stat().st_size > 0:
                    print(f"Already rendered: {output.name}", flush=True)
                    continue

                free_gb = shutil.disk_usage(ROOT).free / (1024 ** 3)
                if free_gb < 10:
                    raise RuntimeError(
                        f"Storage safeguard: only {free_gb:.1f} GB free"
                    )

                run([
                    PYTHON, "scripts/cut.py",
                    str(job),
                    "--pick", str(number),
                    "--layout", "blur",
                    "--captions", "word",
                    "--hook", "GTA VI MOMENT YOU NEED TO SEE"
                ])

            record["status"] = "complete"
            record["completed_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            print(f"COMPLETE: {video_id}", flush=True)

        except Exception as error:
            record["status"] = "failed"
            record["error"] = str(error)
            print(f"FAILED: {video_id}: {error}", flush=True)

        finally:
            history[video_id] = record
            save_history(history)

    print("\n=== PIPELINE FINISHED ===", flush=True)

if __name__ == "__main__":
    main()
