"""Offline editorial-angle detection for gaming commentary."""

import re


THEMES = {
    "mixed_hype": {
        "signals": (
            r"\bexcitement\b",
            r"\blooking forward\b",
            r"\bloving it\b",
            r"\bhating it\b",
        ),
        "topic": "Different reactions to anticipation and hype",
        "angle": "Some gamers feel excited while others disagree",
        "hook": "Does the game deserve the hype?",
        "avoid": (
            "news", "review", "announcement", "release",
            "trailer", "gameplay"
        ),
    },
    "anticipation": {
        "signals": (
            r"\bexcited\b",
            r"\bexcitement\b",
            r"\blooking forward\b",
            r"\bcan't wait\b",
        ),
        "topic": "Anticipation for an upcoming game",
        "angle": "The feeling of looking forward to a game",
        "hook": "What makes a game worth getting excited about?",
        "avoid": ("release", "review", "gameplay"),
    },
    "mixed_opinions": {
        "signals": (
            r"\bopinions\b",
            r"\bloving it\b",
            r"\bhating it\b",
            r"\bdisagree\b",
        ),
        "topic": "Different opinions among gamers",
        "angle": "Not everyone shares the same opinion",
        "hook": "Why do gamers disagree about this game?",
        "avoid": ("controversy", "scandal", "news"),
    },
}

PLATFORM_STYLES = {
    "youtube": "A clear, curiosity-driven question",
    "instagram": "A concise statement emphasizing the disagreement or emotion",
    "tiktok": "A short, conversational hook that invites a reaction",
}


def detect_editorial_angle(transcript, cartridge):
    text = transcript.lower()

    scored = []

    for name, theme in THEMES.items():
        matches = [
            pattern
            for pattern in theme["signals"]
            if re.search(pattern, text, re.IGNORECASE)
        ]
        scored.append((len(matches), name, theme))

    score, name, theme = max(scored, key=lambda item: item[0])

    if score < 2:
        return {
            "theme": "unclassified",
            "confidence": "low",
            "topic": "Discussion about " + cartridge["name"],
            "angle": "Use only the specific claims in the transcript",
            "hook": "",
            "avoid": ["news", "review", "release", "trailer"],
            "platform_styles": PLATFORM_STYLES,
        }

    return {
        "theme": name,
        "confidence": "rule_based",
        "topic": theme["topic"],
        "angle": theme["angle"],
        "hook": theme["hook"],
        "avoid": list(theme["avoid"]),
        "platform_styles": PLATFORM_STYLES,
    }


if __name__ == "__main__":
    import json
    from pathlib import Path
    from cartridges import load_cartridge

    cartridge = load_cartridge("gtavi")
    root = Path(__file__).resolve().parent.parent

    candidates = json.loads(
        (root / "jobs/imtp7rbbema-4a797bec/candidates.json").read_text()
    )["candidates"]

    clip = next(c for c in candidates if int(c["n"]) == 2)
    result = detect_editorial_angle(clip["text"], cartridge)

    print("=== CLIP 2 EDITORIAL ANGLE ===")
    print(json.dumps(result, indent=2))

    assert result["theme"] == "mixed_hype", \
        f"Unexpected theme: {result['theme']}"

    print("\nPASS: Mixed-hype discussion identified.")
    print("PASS: No Ollama or internet required.")
