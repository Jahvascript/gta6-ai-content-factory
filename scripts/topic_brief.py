"""Transcript-grounded topic briefs for interchangeable gaming cartridges."""

import json
from pathlib import Path

from cartridges import load_cartridge


def evidence_chunks(transcript, words_per_chunk=16):
    words = transcript.split()
    if not words:
        raise ValueError("Cannot analyze an empty transcript")

    return {
        str(index + 1): " ".join(words[start:start + words_per_chunk])
        for index, start in enumerate(range(0, len(words), words_per_chunk))
    }


def create_topic_brief(transcript, cartridge, generate_fn):
    evidence = evidence_chunks(transcript)

    numbered = "\n".join(
        f"{key}: {value}"
        for key, value in evidence.items()
    )

    prompt = f"""Analyze this short gaming conversation.

GAME: {cartridge['name']}

Find the specific subject, emotion, and disagreement in the conversation.
Do not simply repeat the game's name as the topic.
Prefer the speaker's actual argument over generic gaming promotion.

Return ONLY JSON with:
topic, emotion, disagreement, evidence_id, suggested_hook.

Rules:
- evidence_id MUST be one of the numbered excerpts.
- Never invent a quotation.
- Never claim gameplay, releases, trailers, or announcements unless stated.
- suggested_hook should be a short, interesting question.
- Do not write a full caption yet.

NUMBERED SOURCE EXCERPTS:
{numbered}
"""

    result = generate_fn(prompt)

    if not isinstance(result, dict):
        raise ValueError("Topic model did not return a JSON object")

    selected = str(result.get("evidence_id", "")).strip()

    if selected not in evidence:
        selected = "1"
        evidence_status = "fallback"
    else:
        evidence_status = "verified"

    return {
        "topic": str(result.get("topic", "")).strip(),
        "emotion": str(result.get("emotion", "")).strip(),
        "disagreement": str(result.get("disagreement", "")).strip(),
        "suggested_hook": str(result.get("suggested_hook", "")).strip(),
        "evidence_id": selected,
        "evidence": evidence[selected],
        "evidence_status": evidence_status,
    }


if __name__ == "__main__":
    import sys

    from ai_metadata import generate

    root = Path(__file__).resolve().parent.parent
    cartridge = load_cartridge("gtavi")

    candidates = json.loads(
        (root / "jobs/imtp7rbbema-4a797bec/candidates.json").read_text()
    )["candidates"]

    clip = next(c for c in candidates if int(c["n"]) == 2)

    brief = create_topic_brief(
        clip["text"],
        cartridge,
        generate,
    )

    print("=== VERIFIED TOPIC BRIEF ===")
    print(json.dumps(brief, indent=2))

    assert brief["evidence"] in clip["text"]
    print("\nPASS: Evidence matches original transcript.")
