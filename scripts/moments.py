"""Find the best clip moments in a video or VOD.

Signals per second: loudness spikes, YouTube "most replayed" heatmap, live-chat spikes
(YouTube VOD chat replay or a TwitchDownloader chat.json) and hype words in the transcript.
Writes jobs/<id>/candidates.md + candidates.json.

usage: python moments.py <url-or-file> [--top 8] [--min 15] [--max 40] [--chat chat.json] [--max-minutes 90]
"""
import argparse, json, math, re, sys, wave
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from common import ffprobe, is_url, job_dir, load_json, run, save_json, tool, ytdlp_base, ytdlp_json

HYPE = re.compile(r"\b(no way|oh my god|omg|what|wait|bro|let'?s go|holy|insane|crazy|yo+|wtf|dude|look at|nah|run|go go)\b", re.I)
CHAT_HYPE = re.compile(r"(LMAO|LOL|KEKW|OMEGALUL|W+\b|CLIP|💀|😂|🔥|NO WAY|HOLY)", re.I)


def fetch(src, d, max_min):
    info = {}
    if is_url(src):
        info = ytdlp_json(src)
        save_json(d / "info.json", {k: info.get(k) for k in ("id", "title", "uploader", "channel", "uploader_id", "webpage_url",
                                                             "duration", "view_count", "upload_date", "heatmap", "is_live", "was_live")})
        vid = d / "source.mp4"
        if not vid.exists():
            args = ytdlp_base() + ["-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b", "--merge-output-format", "mp4",
                                   "-o", str(vid)]
            if max_min > 0 and (info.get("duration") or 0) > max_min * 60:
                args += ["--download-sections", f"*0-{max_min * 60}"]
            run(args + [src])
        if info.get("was_live") and not (d / "chat.json").exists():  # YouTube chat replay
            run(ytdlp_base() + ["--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", str(d / "chat"), src], check=False)
    else:
        vid = Path(src).resolve()
        save_json(d / "info.json", {"title": vid.stem, "webpage_url": str(vid)})
    return vid, info


def audio_rms(vid, d, max_minutes=None):
    wav = d / "audio.wav"
    if not wav.exists():
        command = [tool("ffmpeg"), "-y", "-v", "error", "-i", str(vid)]
        if max_minutes is not None:
            command += ["-t", str(max_minutes * 60)]
        command += ["-ac", "1", "-ar", "16000", str(wav)]
        run(command)
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // 16000
    rms = np.sqrt((x[: n * 16000].reshape(n, 16000) ** 2).mean(1) + 1e-9)
    return wav, 20 * np.log10(rms)


def transcribe(wav, d):
    """Transcribe audio in resumable five-minute chunks."""
    out = d / "transcript.json"
    if out.exists():
        return load_json(out)

    from faster_whisper import WhisperModel

    chunk_dir = d / "transcript_chunks"
    chunk_dir.mkdir(exist_ok=True)

    with wave.open(str(wav)) as audio:
        sample_rate = audio.getframerate()
        channels = audio.getnchannels()
        assert channels == 1 and audio.getsampwidth() == 2
        total_frames = audio.getnframes()

    chunk_frames = sample_rate * 300
    count = (total_frames + chunk_frames - 1) // chunk_frames
    model = None
    words = []

    for index in range(count):
        cache = chunk_dir / f"chunk_{index:04d}.json"

        if cache.exists():
            chunk_words = load_json(cache)
            print(f"Cached chunk {index + 1}/{count}", flush=True)
        else:
            if model is None:
                model = WhisperModel("small", device="cpu", compute_type="int8")

            with wave.open(str(wav)) as audio:
                audio.setpos(index * chunk_frames)
                raw = audio.readframes(min(chunk_frames, total_frames - index * chunk_frames))

            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
            offset = index * 300

            segments, _ = model.transcribe(
                pcm,
                word_timestamps=True,
                vad_filter=True
            )

            chunk_words = [
                {
                    "w": word.word.strip(),
                    "s": round(offset + word.start, 2),
                    "e": round(offset + word.end, 2)
                }
                for segment in segments
                for word in (segment.words or [])
            ]

            save_json(cache, chunk_words)
            print(f"Completed chunk {index + 1}/{count}: {len(chunk_words)} words", flush=True)

        words.extend(chunk_words)

    save_json(out, words)
    return words


def chat_series(d, n, chat_arg, info):
    """Messages per second from YouTube live_chat json lines or a TwitchDownloader chat.json."""
    c = np.zeros(n)
    yt = list(d.glob("chat*.live_chat.json"))
    if yt:
        for line in yt[0].read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                a = json.loads(line)["replayChatItemAction"]
                t = int(a["videoOffsetTimeMsec"]) / 1000
                txt = json.dumps(a["actions"], ensure_ascii=False)
            except Exception:
                continue
            if 0 <= t < n:
                c[int(t)] += 2 if CHAT_HYPE.search(txt) else 1
    elif chat_arg:
        js = load_json(chat_arg)
        for m in js.get("comments", []):
            t = m.get("content_offset_seconds", 0)
            body = (m.get("message") or {}).get("body", "")
            if 0 <= t < n:
                c[int(t)] += 2 if CHAT_HYPE.search(body) else 1
    return c


def z(a):
    a = np.asarray(a, dtype=float)
    if a.std() < 1e-9:
        return np.zeros_like(a)
    return (a - np.median(a)) / (a.std() + 1e-9)


def smooth(a, k):
    k = max(1, int(k))
    return np.convolve(a, np.ones(k) / k, mode="same")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--min", type=float, default=15); ap.add_argument("--max", type=float, default=40)
    ap.add_argument("--chat"); ap.add_argument("--max-minutes", type=int, default=0)
    a = ap.parse_args()
    d = job_dir(a.src)
    vid, info = fetch(a.src, d, a.max_minutes)
    dur = float(ffprobe(vid)["format"]["duration"])
    wav, db = audio_rms(vid, d, a.max_minutes if a.max_minutes > 0 else None)
    n = len(db)
    words = transcribe(wav, d)
    # signals
    loud = smooth(np.clip(z(db - smooth(db, 30)), 0, None), 3)          # jumps above the local level
    hype = np.zeros(n)
    for w in words:
        if HYPE.search(w["w"]) and int(w["s"]) < n:
            hype[int(w["s"])] += 1
    hype = smooth(hype, 5)
    heat = np.zeros(n)
    for h in (info.get("heatmap") or []):
        heat[int(h["start_time"]):int(math.ceil(h["end_time"]))] = h["value"]
    chat = chat_series(d, n, a.chat, info)
    chatz = smooth(np.clip(z(smooth(chat, 10)), 0, None), 3)
    w_heat = 2.0 if heat.any() else 0
    w_chat = 1.5 if chat.any() else 0
    score = 1.0 * loud + 0.8 * z(hype).clip(0) + w_heat * z(heat).clip(0) + w_chat * chatz
    # pick non-overlapping windows around peaks
    starts = [x["s"] for x in words]
    picks, used = [], np.zeros(n, bool)
    order = np.argsort(-score)
    for p in order:
        if len(picks) >= a.top or score[p] <= 0:
            break
        s0 = max(0, p - 0.55 * a.max); e0 = min(dur, s0 + a.max)
        # snap start to the first word after s0 and end to a word end, keep length in [min, max]
        ws = [x for x in words if x["s"] >= s0 and x["e"] <= e0]
        if ws:
            s0 = max(0, ws[0]["s"] - 0.3); e0 = min(dur, ws[-1]["e"] + 0.6)
        if e0 - s0 < a.min:
            e0 = min(dur, s0 + a.min)
        e0 = min(e0, s0 + a.max)
        if used[int(s0):int(e0)].any():
            continue
        used[int(s0):int(e0)] = True
        text = " ".join(x["w"] for x in words if s0 <= x["s"] < e0)
        why = []
        if loud[p] > 1: why.append("loudness spike")
        if hype[p] > 0: why.append("hype words")
        if heat[p] > 0.5: why.append(f"most replayed {heat[p]:.2f}")
        if w_chat and chatz[p] > 1: why.append("chat spike")
        picks.append({"n": len(picks) + 1, "start": round(s0, 2), "end": round(e0, 2), "peak": int(p),
                      "score": round(float(score[p]), 2), "why": why or ["overall energy"], "text": text[:400]})
    picks.sort(key=lambda x: x["start"])
    for i, x in enumerate(picks, 1):
        x["n"] = i
    meta = load_json(d / "info.json")
    save_json(d / "candidates.json", {"source": str(vid), "info": meta, "duration": dur, "candidates": picks,
                                      "signals": {"heatmap": bool(w_heat), "chat": bool(w_chat), "words": len(words)}})
    fmt = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
    md = [f"# Candidates: {meta.get('title', '')}", f"source: {meta.get('webpage_url', '')}",
          f"signals: loudness, transcript ({len(words)} words)" + (", most replayed" if w_heat else "") + (", chat" if w_chat else ""), ""]
    for x in picks:
        md += [f"## {x['n']}. {fmt(x['start'])}-{fmt(x['end'])} ({x['end'] - x['start']:.0f}s) score {x['score']}",
               f"why: {', '.join(x['why'])}", f"> {x['text']}", ""]
    (d / "candidates.md").write_text("\n".join(md), encoding="utf-8")
    print(f"job: {d}\n{len(picks)} candidates -> {d / 'candidates.md'}")


if __name__ == "__main__":
    main()
