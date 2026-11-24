"""Offline-first, read-only publishing eligibility checks."""

from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/publishing_queue.sqlite3"

PLATFORMS = ("youtube", "instagram", "tiktok")


def evaluate(row, rights_cleared=False, publish_authorized=False):
    clip_path, platform, generation, review, title, caption = row

    reasons = []

    if platform not in PLATFORMS:
        reasons.append("unsupported_platform")

    path = Path(clip_path) if clip_path else None

    if not path or not path.is_file():
        reasons.append("missing_video")
    elif path.stat().st_size == 0:
        reasons.append("empty_video")

    if generation != "complete":
        reasons.append("metadata_not_complete")

    if review != "approved":
        reasons.append("metadata_not_approved")

    if not title or not title.strip():
        reasons.append("missing_title")

    if not caption or not caption.strip():
        reasons.append("missing_caption")

    if not rights_cleared:
        reasons.append("rights_not_cleared")

    if not publish_authorized:
        reasons.append("publishing_not_authorized")

    return {
        "clip_path": clip_path,
        "platform": platform,
        "eligible": not reasons,
        "reasons": reasons,
    }


def audit():
    from datetime import datetime, timezone

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    try:
        rows = conn.execute("""
            SELECT
                pq.clip_path,
                pm.platform,
                pm.generation_status,
                pm.review_status,
                pm.title,
                pm.caption,
                COALESCE(pa.rights_cleared, 0),
                COALESCE(pa.publish_authorized, 0),
                sr.ownership_type,
                sr.verified_at,
                sr.revoked_at,
                sr.valid_until,
                COALESCE(sr.modifications_allowed, 0),
                COALESCE(sr.commercial_use_allowed, 0),
                COALESCE(srp.allowed, 0)
            FROM publishing_queue pq
            JOIN platform_metadata pm
                ON pm.clip_path = pq.clip_path
            LEFT JOIN publishing_authorizations pa
                ON pa.source_id = pq.source_id
               AND pa.platform = pm.platform
               AND pa.revoked_at IS NULL
            LEFT JOIN source_rights sr
                ON sr.source_id = pq.source_id
            LEFT JOIN source_rights_platforms srp
                ON srp.source_id = pq.source_id
               AND srp.platform = pm.platform
            ORDER BY pq.clip_number, pm.platform
        """).fetchall()
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    results = []

    for row in rows:
        (
            *base,
            rights_cleared,
            publish_authorized,
            ownership_type,
            verified_at,
            revoked_at,
            valid_until,
            modifications_allowed,
            commercial_use_allowed,
            platform_allowed
        ) = row

        valid_date = True

        if valid_until:
            try:
                expiry = datetime.fromisoformat(
                    valid_until.replace("Z", "+00:00")
                )
                if expiry.tzinfo is None:
                    valid_date = False
                else:
                    valid_date = expiry >= now
            except ValueError:
                valid_date = False

        source_verified = (
            ownership_type in ("original", "licensed", "permission")
            and bool(verified_at)
            and not revoked_at
            and valid_date
            and bool(modifications_allowed)
            and bool(platform_allowed)
        )

        # Commercial-use permission is checked separately by
        # the eventual monetization workflow.
        result = evaluate(
            tuple(base),
            rights_cleared=bool(rights_cleared) and source_verified,
            publish_authorized=bool(publish_authorized)
        )

        if not source_verified:
            result["reasons"].append("source_rights_not_verified")
            result["eligible"] = False

        results.append(result)

    return results


if __name__ == "__main__":
    from collections import Counter

    results = audit()

    print("=== PUBLISHING ELIGIBILITY AUDIT ===")
    print("Platform drafts:", len(results))
    print("Eligible:", sum(r["eligible"] for r in results))

    counts = Counter(
        reason
        for result in results
        for reason in result["reasons"]
    )

    print("\\nBlocking reasons:")
    for reason, count in sorted(counts.items()):
        print(f"  {reason}: {count}")

    print("\\nREAD-ONLY AUDIT COMPLETE")
    print("No uploads or publishing.")
