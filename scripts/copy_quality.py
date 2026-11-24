"""Offline quality checks for platform-specific gaming copy."""

import re
from difflib import SequenceMatcher


GENERIC_PHRASES = (
    "what do you think about",
    "share your thoughts in the comments",
    "let's talk about it",
    "let's chat in the comments",
    "what's your take",
    "comment below",
)

UNSUPPORTED_FRAMING = (
    "reception of grand theft auto vi",
    "hype vs. reality",
    "excited or disappointed",
)


def normalize(text):
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def check_copy(item, transcript, angle):
    issues = []

    title = normalize(item.get("title", ""))
    caption = normalize(item.get("caption", ""))
    comment = normalize(item.get("first_comment", ""))
    cta = normalize(item.get("cta", ""))

    if any(phrase in caption for phrase in GENERIC_PHRASES):
        issues.append("generic caption")

    combined = title + " " + caption + " " + comment

    unsupported_pattern = re.search(
        r"\b(?:hype|excitement|expectations|anticipation)"
        r"\s+(?:vs\.?|versus)\s+reality\b",
        combined,
    )

    if (
        any(phrase in combined for phrase in UNSUPPORTED_FRAMING)
        or unsupported_pattern
    ):
        issues.append("potentially unsupported framing")

    if any(phrase in comment for phrase in GENERIC_PHRASES):
        issues.append("generic first comment")

    source_details = (
        "biggest gta fan",
        "enjoyed it",
        "opinions",
        "loving it",
        "hating it",
        "excitement in your stomach",
    )

    if (
        any(detail in normalize(transcript) for detail in source_details)
        and not any(
            keyword in caption
            for keyword in (
                "fan", "enjoy", "opinion", "love",
                "hate", "loving", "hating",
                "stomach", "personal experience",
            )
        )
    ):
        issues.append("caption lacks transcript-specific detail")

    if len(caption.split()) < 12:
        issues.append("caption lacks substance")

    if SequenceMatcher(None, caption, comment).ratio() > 0.75:
        issues.append("caption and first comment too similar")

    if angle.get("theme") == "mixed_hype":
        discussion_words = (
            "hype", "excited", "excitement",
            "anticipation", "skeptical", "skepticism",
            "opinions", "disagree", "different"
        )
        if not any(word in caption for word in discussion_words):
            issues.append("caption misses the central discussion")

    return issues


if __name__ == "__main__":
    import json
    import sqlite3
    from pathlib import Path

    from cartridges import load_cartridge
    from editorial_angle import detect_editorial_angle

    game = load_cartridge("gtavi")
    candidates = json.loads(
        Path("jobs/imtp7rbbema-4a797bec/candidates.json").read_text()
    )["candidates"]

    clip = next(c for c in candidates if int(c["n"]) == 2)
    angle = detect_editorial_angle(clip["text"], game)

    conn = sqlite3.connect("data/publishing_queue.sqlite3")

    rows = conn.execute("""
        SELECT pm.platform, pm.title, pm.caption,
               pm.first_comment, pm.cta
        FROM platform_metadata pm
        JOIN publishing_queue pq ON pq.clip_path = pm.clip_path
        WHERE pq.source_id=? AND pq.clip_number=?
        ORDER BY pm.platform
    """, ("ImTp7RbbemA", 2)).fetchall()

    assert len(rows) == 3

    print("=== CLIP 2 COPY QUALITY AUDIT ===")

    for platform, title, caption, comment, cta in rows:
        item = {
            "title": title,
            "caption": caption,
            "first_comment": comment,
            "cta": cta,
        }

        issues = check_copy(item, clip["text"], angle)

        print(f"\n{platform.upper()}")
        print("Title:", title)
        print("Caption:", caption)
        print("Quality issues:", issues or "none")

    conn.close()

    print("\nPASS: Read-only quality audit completed.")
    print("No drafts modified or published.")
