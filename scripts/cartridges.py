"""Offline-first configuration loader for interchangeable gaming cartridges."""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARTRIDGE_DIR = ROOT / "config" / "cartridges"

REQUIRED = (
    "name",
    "search_queries",
    "keywords",
    "hashtags",
    "tone",
    "enabled",
)


def load_cartridge(slug="gtavi", require_enabled=True):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise ValueError(f"Invalid cartridge name: {slug!r}")

    path = CARTRIDGE_DIR / f"{slug}.json"

    if not path.is_file():
        available = ", ".join(
            p.stem for p in sorted(CARTRIDGE_DIR.glob("*.json"))
        )
        raise FileNotFoundError(
            f"Cartridge {slug!r} not found. Available: {available}"
        )

    data = json.loads(path.read_text(encoding="utf-8"))

    missing = [field for field in REQUIRED if field not in data]
    if missing:
        raise ValueError(f"{slug}: missing fields: {', '.join(missing)}")

    for field in ("search_queries", "keywords", "hashtags"):
        values = data[field]
        if not isinstance(values, list) or not values or not all(
            isinstance(value, str) and value.strip()
            for value in values
        ):
            raise ValueError(f"{slug}: {field} must be a nonempty string list")

    if not isinstance(data["enabled"], bool):
        raise ValueError(f"{slug}: enabled must be true or false")

    if require_enabled and not data["enabled"]:
        raise ValueError(
            f"Cartridge {slug!r} is disabled. Configure and enable it first."
        )

    data["slug"] = slug

    # GTA VI's primary discoverability hashtag.
    if slug == "gtavi":
        tags = data["hashtags"]
        data["hashtags"] = ["#GTA6"] + [
            tag for tag in tags if tag.lower() != "#gta6"
        ]

    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cartridge", default="gtavi",
        help="Cartridge name, such as gtavi, madden, or rpg",
    )
    parser.add_argument(
        "--inspect-disabled",
        action="store_true",
        help="Allow inspection of inactive cartridge configurations",
    )
    args = parser.parse_args()

    cartridge = load_cartridge(
        args.cartridge,
        require_enabled=not args.inspect_disabled,
    )

    print(json.dumps(cartridge, indent=2))
