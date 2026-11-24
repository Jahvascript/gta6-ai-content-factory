"""Generate offline draft publishing metadata from clip transcripts."""
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data/publishing_queue.sqlite3"
JOB = ROOT / "jobs/imtp7rbbema-4a797bec"

data = json.loads((JOB / "candidates.json").read_text())
candidates = {int(c["n"]): c for c in data["candidates"]}

transcript = json.loads((JOB / "transcript.json").read_text())

def clean(text):
    return re.sub(r"\\s+", " ", text).strip()

def make_title(text, number):
    sentences = re.split(r"(?<=[.!?])\\s+", text)
    sentences = [clean(x) for x in sentences if len(clean(x)) >= 15]

    hook = sentences[0] if sentences else text
    words = hook.split()

    if len(words) > 12:
        hook = " ".join(words[:12]).rstrip(",.!?") + "..."

    return f"{hook} | GTA VI" if hook else f"GTA VI Highlight #{number}"

conn = sqlite3.connect(DB)

conn.execute("""
CREATE TABLE IF NOT EXISTS clip_metadata (
    clip_path TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    hashtags TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    FOREIGN KEY (clip_path)
        REFERENCES publishing_queue(clip_path)
)
""")

conn.execute("""
ALTER TABLE clip_metadata ADD COLUMN first_comment TEXT
""") if "first_comment" not in {
    row[1] for row in conn.execute("PRAGMA table_info(clip_metadata)")
} else None

conn.execute("""
ALTER TABLE clip_metadata ADD COLUMN cta TEXT
""") if "cta" not in {
    row[1] for row in conn.execute("PRAGMA table_info(clip_metadata)")
} else None

rows = conn.execute("""
SELECT clip_path, clip_number
FROM publishing_queue
WHERE source_id = ?
ORDER BY clip_number
""", ("ImTp7RbbemA",)).fetchall()

now = datetime.now(timezone.utc).isoformat()

for clip_path, number in rows:
    candidate = candidates[number]
    start = float(candidate["start"])
    end = float(candidate["end"])

    excerpt = clean(candidate.get("text", ""))

    if not excerpt:
        raise ValueError(f"Candidate {number} has no transcript text")

    title = make_title(excerpt, number)
    description = (
        f"GTA VI discussion highlight.\n\n"
        f"{excerpt[:350]}\n\n"
        f"Follow for more GTA VI moments."
    )
    hashtags = "#GTA6 #GTAVI #GrandTheftAuto #Gaming #Shorts"

    first_comment = "What's your take on this GTA VI discussion?"
    cta = "Share your thoughts below and follow for more GTA VI updates."

    conn.execute("""
    INSERT INTO clip_metadata
    (clip_path, title, description, hashtags, generated_at,
     first_comment, cta)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(clip_path) DO UPDATE SET
        title = excluded.title,
        description = excluded.description,
        hashtags = excluded.hashtags,
        generated_at = excluded.generated_at,
        first_comment = excluded.first_comment,
        cta = excluded.cta
    """, (clip_path, title, description, hashtags, now,
          first_comment, cta))

conn.commit()

count = conn.execute("SELECT COUNT(*) FROM clip_metadata").fetchone()[0]

print(f"PASS: {count} metadata drafts stored.")
print("\n=== FIRST FIVE DRAFT TITLES ===")

for number, title in conn.execute("""
SELECT q.clip_number, m.title
FROM publishing_queue q
JOIN clip_metadata m ON q.clip_path = m.clip_path
ORDER BY q.clip_number
LIMIT 5
"""):
    print(f"Clip {number}: {title}")

print("\nNo videos were uploaded, scheduled, or published.")
conn.close()
