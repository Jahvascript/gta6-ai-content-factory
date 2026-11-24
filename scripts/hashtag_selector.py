"""Offline, cartridge-aware hashtag selection."""

import re


TOPIC_TAGS = {
    "mixed_hype": ["#GTA6Hype", "#GamingDiscussion"],
    "anticipation": ["#GTA6Hype", "#GamingCommunity"],
    "mixed_opinions": ["#GamingDiscussion", "#GamingCommunity"],
    "unclassified": ["#Gaming", "#GamingCommunity"],
}

GENERAL_TAGS = {
    "gtavi": [
        "#GTA6", "#GTAVI", "#RockstarGames",
        "#GrandTheftAuto", "#Gaming", "#GamingCommunity"
    ],
}


def select_hashtags(cartridge, angle, platform):
    slug = cartridge["slug"]
    primary = cartridge["hashtags"][0]

    general = GENERAL_TAGS.get(
        slug,
        [primary] + list(cartridge["hashtags"][1:])
    )

    # GTA-specific themes must not leak into other cartridges.
    if slug == "gtavi":
        topical = TOPIC_TAGS.get(
            angle.get("theme", "unclassified"),
            TOPIC_TAGS["unclassified"]
        )
    else:
        topical = ["#Gaming", "#GamingCommunity"]

    # Different platform ordering, same approved vocabulary.
    if platform == "youtube":
        candidates = [primary] + topical + general
    elif platform == "instagram":
        candidates = [primary] + general[1:3] + topical + general
    elif platform == "tiktok":
        candidates = [primary] + topical + general[1:]
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    selected = []
    seen = set()

    for tag in candidates:
        if not re.fullmatch(r"#[A-Za-z0-9_]+", tag):
            continue
        key = tag.lower()
        if key not in seen:
            selected.append(tag)
            seen.add(key)
        if len(selected) == 5:
            break

    assert selected[0].lower() == primary.lower()
    assert 3 <= len(selected) <= 5

    return " ".join(selected)


if __name__ == "__main__":
    from cartridges import load_cartridge
    from editorial_angle import detect_editorial_angle

    game = load_cartridge("gtavi")
    transcript = (
        "There's excitement when looking forward to a game, "
        "but some people loving it and some people hating it."
    )
    angle = detect_editorial_angle(transcript, game)

    assert angle["theme"] == "mixed_hype"

    forbidden = (
        "release", "anniversary", "revealed",
        "review", "news", "hypewar"
    )

    for platform in ("youtube", "instagram", "tiktok"):
        tags = select_hashtags(game, angle, platform)

        assert tags.split()[0] == "#GTA6"
        assert 3 <= len(tags.split()) <= 5
        assert not any(word in tags.lower() for word in forbidden)

        print(f"PASS: {platform}: {tags}")

    print("\nPASS: Deterministic hashtags ready.")
    print("No Ollama calls, database changes, or publishing.")
