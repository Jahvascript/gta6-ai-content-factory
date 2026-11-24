"""Offline cross-platform metadata uniqueness checks."""

import re
from difflib import SequenceMatcher


def normalize(text):
    text = str(text).lower()

    # Normalize equivalent GTA VI references before comparison.
    text = re.sub(r"#?gta[ _-]?(?:vi|6)\\b", "gta6", text)
    text = re.sub(r"grand theft auto[ _-]?(?:vi|6)\\b", "gta6", text)

    # Remove other hashtags while retaining their words.
    text = text.replace("#", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)

    return " ".join(text.split())


def similarity(first, second):
    a = normalize(first)
    b = normalize(second)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def check_platform_uniqueness(drafts, threshold=0.88):
    """Return issues keyed by platform.

    drafts: {platform: {title: str, caption: str, ...}}
    """
    issues = {platform: [] for platform in drafts}
    platforms = sorted(drafts)

    for index, first in enumerate(platforms):
        for second in platforms[index + 1:]:
            for field in ("title", "caption"):
                score = similarity(
                    drafts[first].get(field, ""),
                    drafts[second].get(field, ""),
                )

                if score >= threshold:
                    message = (
                        f"near-duplicate {field} across "
                        f"{first} and {second} "
                        f"(similarity={score:.2f})"
                    )
                    issues[first].append(message)
                    issues[second].append(message)

    return issues


def check_against_existing(platform, draft, existing, threshold=0.88):
    """Check one draft against other platforms for the same clip."""
    issues = []

    for other_platform, other_draft in existing.items():
        if other_platform == platform:
            continue

        for field in ("title", "caption"):
            score = similarity(
                draft.get(field, ""),
                other_draft.get(field, ""),
            )

            if score >= threshold:
                issues.append(
                    f"near-duplicate {field} compared with "
                    f"{other_platform} (similarity={score:.2f})"
                )

    return issues
