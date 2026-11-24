"""Deterministic, transcript-grounded evidence extraction."""

import re


STOPWORDS = {
    "about", "after", "again", "could", "every", "from",
    "have", "into", "just", "like", "more", "some",
    "that", "their", "there", "these", "they", "this",
    "those", "very", "what", "when", "where", "which",
    "while", "with", "would", "your"
}


def tokens(text):
    return set(
        word for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) >= 4 and word not in STOPWORDS
    )


def select_evidence(transcript, cartridge, chunk_words=32, limit=3):
    words = transcript.split()

    if not words:
        raise ValueError("Cannot extract evidence from empty transcript")

    keywords = set()

    for value in cartridge.get("keywords", []):
        keywords.update(tokens(value))

    keywords.update(tokens(cartridge.get("name", "")))

    chunks = []

    for index, start in enumerate(range(0, len(words), chunk_words)):
        text = " ".join(words[start:start + chunk_words])
        found = tokens(text)

        score = len(found & keywords)

        # Prioritize discussion-bearing language.
        discussion = {
            "excited", "excitement", "hype", "opinions",
            "loving", "hating", "disagree", "expectations",
            "review", "rating", "perfect", "controversy"
        }

        score += len(found & discussion)

        chunks.append({
            "index": index,
            "start_word": start,
            "text": text,
            "score": score
        })

    ranked = sorted(
        chunks,
        key=lambda item: (-item["score"], item["index"])
    )

    selected = sorted(
        ranked[:limit],
        key=lambda item: item["index"]
    )

    return {
        "evidence_status": "deterministic",
        "evidence": [item["text"] for item in selected],
        "source_word_count": len(words),
        "selected_chunks": len(selected)
    }
