"""Offline, resumable, review-gated metadata drafting via Ollama."""
import argparse
import json
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from cartridges import load_cartridge
from source_evidence import select_evidence
from editorial_angle import detect_editorial_angle
from hashtag_selector import select_hashtags

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data/publishing_queue.sqlite3"
DEFAULT_JOB = ROOT / "jobs/imtp7rbbema-4a797bec"
MODEL = "qwen2.5:1.5b"
PLATFORMS = ("youtube", "instagram", "tiktok")

from copy_quality import check_copy, UNSUPPORTED_FRAMING
from platform_uniqueness import check_against_existing

def now():
    return datetime.now(timezone.utc).isoformat()

def generate(prompt):
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.25,
            "num_ctx": 2048,
            "num_predict": 420
        },
        "keep_alive": 0
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        result = json.load(response)
    return json.loads(result["response"])

def normalize_hashtags(value):
    if isinstance(value, list):
        tags = [str(x).strip().lstrip("#") for x in value]
    elif isinstance(value, str):
        tags = re.findall(r"#[A-Za-z0-9_]+", value)
        tags = [x.lstrip("#") for x in tags]
    else:
        tags = []
    tags = [x for x in tags if re.fullmatch(r"[A-Za-z0-9_]+", x)]
    return " ".join("#" + x for x in dict.fromkeys(tags))

PLATFORM_TAGS = {
    "youtube": "#GamingShorts",
    "instagram": "#GamingReels",
    "tiktok": "#GamingTikTok",
}


def cartridge_hashtags(cartridge, platform):
    tags = list(cartridge["hashtags"])
    tags.append(PLATFORM_TAGS[platform])
    return normalize_hashtags(tags[:5])


def enforce_primary_hashtag(item, cartridge, platform):
    primary = cartridge["hashtags"][0]
    generated = normalize_hashtags(item.get("hashtags"))
    tags = generated.split()

    tags = [tag for tag in tags if tag.lower() != primary.lower()]
    tags = [primary] + tags

    if len(tags) < 3:
        tags = cartridge_hashtags(cartridge, platform).split()

    item["hashtags"] = " ".join(tags[:5])
    return item


NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20
}

def mentioned_numbers(text, cartridge=None):
    # Remove known game-title numerals before comparing factual numbers.
    if cartridge:
        for keyword in cartridge["keywords"]:
            text = re.sub(re.escape(keyword), "GAME", text, flags=re.I)
    else:
        text = re.sub(r"\bGTA\s*(?:6|VI)\b", "GTA", text, flags=re.I)

    values = set()

    for number in re.findall(r"\b\d+(?:\.\d+)?\b", text):
        values.add(float(number))

    for word, value in NUMBER_WORDS.items():
        if re.search(r"\b" + word + r"\b", text, re.I):
            values.add(float(value))

    return values


def validate(item, transcript, platform, cartridge=None):
    errors = []

    for key in ("title", "caption", "hashtags", "first_comment", "cta"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            errors.append(f"missing {key}")

    if errors:
        return errors

    if len(item["title"]) > 85:
        errors.append("title too long")

    if "?" not in item["first_comment"]:
        errors.append("first comment must ask a question")

    if cartridge and cartridge["slug"] == "gtavi" and "#gta7" in item["hashtags"].lower():
        errors.append("irrelevant GTA7 hashtag")

    tags = item["hashtags"].split()
    if not 3 <= len(tags) <= 5:
        if cartridge:
            item["hashtags"] = cartridge_hashtags(cartridge, platform)
        else:
            item["hashtags"] = "#GTA6 #GTAVI #RockstarGames"

    text = "\n".join(
        str(item[key]) for key in
        ("title", "caption", "first_comment", "cta")
    )

    # Flag first-person claims about the source commentator's activities.
    impersonation = False
    for sentence in re.split(r"[.!?\n]+", text):
        speaker = re.search(
            r"\b(?:i(?:'ve|'m|'d)?|my|we(?:'ve|'re)?|our)\b",
            sentence, re.I
        )
        activity = re.search(
            r"\b(?:stream(?:ed|ing)?|play(?:ed|ing)?|"
            r"nap(?:ped|ping)?|gameplay)\b",
            sentence, re.I
        )
        if speaker and activity:
            impersonation = True
            break

    if impersonation:
        errors.append("possible commentator impersonation")

    # Reject first-person personal claims by the publishing account.
    first_person_claims = re.search(
        r"\b(?:I'm|I am|I've|I have|I was|I played|"
        r"I think|I feel|I'm sure|we've|we are|we were)\b",
        text, re.I
    )
    if first_person_claims:
        errors.append("first-person personal claim")

    # Reject generic marketing and unsupported release language.
    marketing_claims = re.search(
        r"\b(?:finally here|out now|available now|"
        r"officially released|game that changed everything|"
        r"ultimate gaming experience|latest updates)\b",
        text, re.I
    )
    if marketing_claims:
        errors.append("generic or potentially unsupported marketing claim")

    # Keep other GTA titles out of GTA VI metadata.
    if cartridge and cartridge["slug"] == "gtavi":
        if re.search(r"#(?:GTAIV|GTA4|GTAV|GTA5)\b", item["hashtags"], re.I):
            errors.append("unrelated GTA game hashtag")

    unsupported = mentioned_numbers(text, cartridge) - mentioned_numbers(transcript, cartridge)

    if unsupported:
        errors.append(f"unsupported numbers: {sorted(unsupported)}")

    # Flag misleading hashtags when unsupported by the clip's theme.
    if cartridge is not None:
        detected = detect_editorial_angle(transcript, cartridge)
        forbidden = set(detected.get("avoid", []))
        tags = item["hashtags"].lower().split()

        for tag in tags:
            for subject in ("news", "review", "announcement", "gameplay"):
                if subject in forbidden and subject in tag:
                    errors.append(f"unsupported {subject} hashtag")

    # EDITORIAL HASHTAG VALIDATION V1
    if cartridge is not None:
        detected = detect_editorial_angle(transcript, cartridge)
        forbidden = set(detected.get("avoid", []))
        tags = item["hashtags"].lower().split()

        for tag in tags:
            for subject in ("news", "review", "announcement", "gameplay"):
                if subject in forbidden and subject in tag:
                    errors.append(f"unsupported {subject} hashtag")

    # AUTOMATIC COPY QUALITY GATE V1
    if cartridge is not None:
        angle = detect_editorial_angle(transcript, cartridge)
        for issue in check_copy(item, transcript, angle):
            if issue not in errors:
                errors.append(issue)

    return errors

def draft_for_platform(transcript, platform, cartridge, brief=None, angle=None, retry_feedback=None, previous_draft=None):
    prohibited_framing = ", ".join(UNSUPPORTED_FRAMING)
    name = cartridge["name"]
    tone = cartridge["tone"]
    primary = cartridge["hashtags"][0]
    keywords = ", ".join(cartridge["keywords"])
    brief = brief or {}
    angle = angle or {}
    editorial_topic = angle.get("topic", "")
    editorial_angle = angle.get("angle", "")
    editorial_hook = angle.get("hook", "")
    editorial_avoid = ", ".join(angle.get("avoid", []))
    platform_style = angle.get("platform_styles", {}).get(platform, "")
    topic = brief.get("topic", "")
    emotion = brief.get("emotion", "")
    disagreement = brief.get("disagreement", "")
    evidence = brief.get("evidence", "")
    hook = brief.get("suggested_hook", "")

    prompt = f"""Create short, engaging social media metadata for a gaming video.

PLATFORM: {platform}
GAME: {name}
TONE: {tone}

VIDEO TRANSCRIPT:
{transcript[:3000]}

RULES:
- The transcript is your only factual source.
- Focus on ONE interesting detail actually mentioned.
- Never invent gameplay, fixes, features, events, quotes, or personal history.
- The speaker's opinions are opinions, not verified facts.
- Do not write as if you are the speaker.
- Do not claim you played or streamed the game.
- Do not assume gameplay footage is shown.
- Avoid generic hype, exaggerated claims, and invented context.
- Title: short, specific, interesting, approximately 5-12 words.
- Caption: 1-2 short sentences describing the actual discussion.
- First comment: one relevant question viewers can answer.
- CTA: short and natural.
- Hashtags: use {primary} first; Python will finalize hashtags.
- No introductions like "Hey gamers!" or "Let's dive in!"
- Prioritize accuracy over creativity.
- Return ONLY a JSON object with these five string fields:
  title, caption, hashtags, first_comment, cta.
"""
    if retry_feedback:
        previous = json.dumps(
            previous_draft or {}, ensure_ascii=False
        )
        prompt += (
            '\nREVISION REQUIRED:\n'
            'PREVIOUS DRAFT:\n' + previous + '\n'
            'VALIDATION FAILURES:\n'
            + '\n'.join('- ' + issue for issue in retry_feedback)
            + '\nRewrite the previous draft to fix every failure. '
              'Keep accurate, specific details from the transcript. '
              'Do not invent skepticism, disappointment, reception, '
              'reviews, or gameplay claims unless supported by the '
              'source transcript. Write a substantive caption of at '
              'least 12 words. Avoid generic engagement bait. '
              'Return only the required JSON.\n'
        )

    item = generate(prompt)
    if isinstance(item, dict):
        enforce_primary_hashtag(item, cartridge, platform)
    # DETERMINISTIC HASHTAGS V1
    # The AI may suggest tags, but only Python-approved tags are stored.
    if isinstance(item, dict):
        selected_angle = angle or detect_editorial_angle(
            transcript, cartridge
        )
        item["hashtags"] = select_hashtags(
            cartridge, selected_angle, platform
        )

    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip", type=int, required=True)
    parser.add_argument("--cartridge", default="gtavi")
    parser.add_argument("--job", help="Existing job directory or job ID")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cartridge = load_cartridge(args.cartridge)
    source_id = cartridge.get("source_id")
    if not source_id:
        raise SystemExit("Cartridge needs a source_id before metadata generation")

    if args.job:
        job = Path(args.job)
        if not job.is_dir():
            job = ROOT / "jobs" / args.job
    elif cartridge["slug"] == "gtavi":
        job = DEFAULT_JOB
    else:
        raise SystemExit("Specify --job for this cartridge")

    candidates = json.loads((job / "candidates.json").read_text())["candidates"]
    candidate = next(
        (x for x in candidates if int(x["n"]) == args.clip), None
    )
    if candidate is None:
        raise SystemExit(f"Clip {args.clip} not found")

    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT clip_path FROM publishing_queue WHERE source_id=? AND clip_number=?",
        (source_id, args.clip)
    ).fetchone()
    if not row:
        raise SystemExit("Clip not found in publishing queue")

    clip_path = row[0]
    transcript = candidate["text"]

    # Extract evidence locally without relying on AI-selected IDs.
    # All excerpts come directly from the candidate transcript.
    evidence = select_evidence(transcript, cartridge)

    brief = {
        "topic": "",
        "emotion": "",
        "disagreement": "",
        "evidence": " ".join(evidence["evidence"]),
        "suggested_hook": "",
        "evidence_status": evidence["evidence_status"]
    }

    print("EVIDENCE STATUS:", brief["evidence_status"], flush=True)
    print("EVIDENCE WORDS:", evidence["source_word_count"], flush=True)
    print("SELECTED CHUNKS:", evidence["selected_chunks"], flush=True)
    print("EVIDENCE:", brief["evidence"], flush=True)

    angle = detect_editorial_angle(transcript, cartridge)
    print("EDITORIAL THEME:", angle["theme"], flush=True)
    print("EDITORIAL ANGLE:", angle["angle"], flush=True)

    for platform in PLATFORMS:
        state = conn.execute("""
            SELECT generation_status, review_status
            FROM platform_metadata
            WHERE clip_path=? AND platform=?
        """, (clip_path, platform)).fetchone()

        if not state:
            print(f"SKIP {platform}: no database row", flush=True)
            continue

        generation_status, review_status = state
        if review_status != "pending":
            print(f"PROTECTED {platform}: review status={review_status}", flush=True)
            continue
        if generation_status == "complete" and not args.force:
            print(f"SKIP {platform}: already generated", flush=True)
            continue

        print(f"\n=== CLIP {args.clip} / {platform.upper()} ===", flush=True)

        try:
            existing_rows = conn.execute("""
                SELECT platform, title, caption
                FROM platform_metadata
                WHERE clip_path=?
                  AND platform<>?
                  AND generation_status IN ('complete', 'needs_review')
            """, (clip_path, platform)).fetchall()

            existing = {
                name: {"title": title or "", "caption": caption or ""}
                for name, title, caption in existing_rows
            }

            def check_draft(draft):
                problems = validate(
                    draft, transcript, platform, cartridge
                )
                if isinstance(draft, dict):
                    problems.extend(
                        check_against_existing(
                            platform, draft, existing
                        )
                    )
                return list(dict.fromkeys(problems))

            item = draft_for_platform(
                transcript, platform, cartridge, brief, angle
            )
            errors = check_draft(item)

            # High-throughput mode: one AI draft per platform.
            # Minor copy imperfections do not block production.
            blocking = [
                error for error in errors
                if any(term in error.lower() for term in (
                    "unsupported",
                    "misleading",
                    "impersonat",
                    "missing",
                    "invalid",
                    "fabricat",
                ))
            ]
            if errors:
                print("QUALITY NOTES:", "; ".join(errors), flush=True)
            errors = blocking


            status = "complete" if not errors else "needs_review"
        except Exception as exc:
            item = {}
            errors = [f"{type(exc).__name__}: {exc}"]
            status = "failed"

        conn.execute("""
            UPDATE platform_metadata
            SET title=?, caption=?, hashtags=?, first_comment=?, cta=?,
                generation_status=?, validation_errors=?,
                model=?, generated_at=?
            WHERE clip_path=? AND platform=? AND review_status='pending'
        """, (
            item.get("title", ""),
            item.get("caption", ""),
            item.get("hashtags", ""),
            item.get("first_comment", ""),
            item.get("cta", ""),
            status, json.dumps(errors), MODEL, now(),
            clip_path, platform
        ))
        conn.commit()

        print("STATUS:", status, flush=True)
        print("TITLE:", item.get("title", ""), flush=True)
        print("CAPTION:", item.get("caption", ""), flush=True)
        print("HASHTAGS:", item.get("hashtags", ""), flush=True)
        print("FIRST COMMENT:", item.get("first_comment", ""), flush=True)
        print("CTA:", item.get("cta", ""), flush=True)
        if errors:
            print("VALIDATION:", "; ".join(errors), flush=True)

    conn.close()
    print("\nDONE. Nothing uploaded or published.")

if __name__ == "__main__":
    main()
