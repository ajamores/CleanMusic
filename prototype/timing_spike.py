#!/usr/bin/env python3
"""
PROTOTYPE — throwaway. Where does the time GO, and how do we make it fast?
Measures per-stage latency + counts MusicBrainz calls. 6 representative songs.

Stages timed per song: download(yt-dlp) | convert(ffmpeg) | shazam | musicbrainz
                        | llm-min(opus) | llm-fusion(opus) | llm-min(haiku)
MB uses the FAST path: 2 calls/song (get-by-isrc + browse_releases), not the old ~9.

Run:  python3 prototype/timing_spike.py
"""
import asyncio, base64, glob, json, os, re, subprocess, sys, tempfile, time, urllib.request

import anthropic, musicbrainzngs
from dotenv import load_dotenv
from shazamio import Shazam

load_dotenv()
musicbrainzngs.set_useragent("muzik-prototype", "0.0", "armand.amores1@gmail.com")
llm = anthropic.Anthropic()

OPUS, HAIKU, EFFORT = "claude-opus-5", "claude-haiku-4-5", "medium"
STUDIO_BADGES = {"compilation", "live", "remix", "dj-mix", "mixtape", "demo", "soundtrack"}
MB_CALLS = [0]
STAGE = {}   # name -> list of seconds

SONGS = [
    ("mainstream",   "Daft Punk Get Lucky ft Pharrell"),
    ("french",       "Stromae Alors on danse"),
    ("classical",    "Beethoven Moonlight Sonata 3rd movement"),
    ("instrumental", "Deadmau5 Strobe"),
    ("japanese",     "YOASOBI Yoru ni Kakeru official"),
    ("sped-up",      "Metro Boomin Creepin sped up"),
]


class timed:
    def __init__(self, name): self.name = name
    def __enter__(self): self.t = time.perf_counter(); return self
    def __exit__(self, *a): STAGE.setdefault(self.name, []).append(time.perf_counter() - self.t)


def dig(track, key):
    if key.lower() == "isrc" and track.get("isrc"): return track["isrc"]
    for sec in track.get("sections", []):
        for md in sec.get("metadata", []) or []:
            if str(md.get("title", "")).lower() == key.lower(): return md.get("text")
    return None


def mb_by_isrc(isrc):
    """FAST path: 2 calls total — get recording by ISRC, then browse its releases w/ types."""
    if not isrc: return "no ISRC"
    MB_CALLS[0] += 1
    recs = musicbrainzngs.get_recordings_by_isrc(isrc, includes=["releases"])["isrc"]["recording-list"]
    if not recs: return "no recording"
    MB_CALLS[0] += 1
    rels = musicbrainzngs.browse_releases(recording=recs[0]["id"], includes=["release-groups"], limit=100)["release-list"]
    best, best_date = None, "9999"
    for rel in rels:
        rg = rel.get("release-group", {})
        primary = (rg.get("primary-type") or rg.get("type") or "").lower()
        secondary = {s.lower() for s in rg.get("secondary-type-list", [])}
        if primary != "album" or (secondary & STUDIO_BADGES): continue
        date = rel.get("date", "9999") or "9999"
        if date < best_date: best, best_date = rel, date
    if best: return f"{best['title']} [studio]"
    return f"{rels[0]['title']} [other]" if rels else "no release"


def thumb_block(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data, mt = r.read(), r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    if mt not in ("image/jpeg", "image/png", "image/webp", "image/gif"): mt = "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": mt,
            "data": base64.standard_b64encode(data).decode()}}


def ask(content, model):
    # Haiku 4.5 predates adaptive thinking + effort — call it plainly.
    extra = {} if "haiku" in model else {"thinking": {"type": "adaptive"}, "output_config": {"effort": EFFORT}}
    resp = llm.messages.create(
        model=model, max_tokens=1500, **extra,
        system=("You identify the real recording behind a YouTube music video. Reply with ONLY JSON: "
                '{"artist": str, "title": str, "album": str|null, "confidence": 0-1}. No prose.'),
        messages=[{"role": "user", "content": content}])
    txt = next((b.text for b in resp.content if b.type == "text"), "{}")
    m = re.search(r"\{.*\}", txt, re.S)
    try: d = json.loads(m.group(0) if m else txt)
    except Exception: d = {"album": "PARSE FAIL"}
    return d.get("album")


async def run():
    shazam = Shazam()
    for label, query in SONGS:
        print(f"[{label}] {query}", file=sys.stderr)
        try:
          with tempfile.TemporaryDirectory() as d:
            with timed("download"):
                subprocess.run(["yt-dlp", "-f", "bestaudio", "--no-playlist", "--write-info-json",
                    "-o", os.path.join(d, "%(id)s.%(ext)s"), "--quiet", "--no-warnings",
                    f"ytsearch1:{query}"], check=True)
            info = json.load(open(glob.glob(os.path.join(d, "*.info.json"))[0]))
            raw = next(p for p in glob.glob(os.path.join(d, "*")) if not p.endswith(".info.json"))
            wav = os.path.join(d, "clean.wav")
            with timed("convert"):
                subprocess.run(["ffmpeg", "-y", "-i", raw, "-ac", "1", "-ar", "16000", wav],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with timed("shazam"):
                try: out = await shazam.recognize(wav)
                except AttributeError: out = await shazam.recognize_song(wav)
                except Exception: out = {}
            tr = out.get("track") or {}
            with timed("musicbrainz"):
                mb_by_isrc(dig(tr, "ISRC"))

            thumb = None
            if info.get("thumbnail"):
                try: thumb = thumb_block(info["thumbnail"])
                except Exception: pass
            cmin = [{"type": "text", "text": f'YouTube video title: "{info.get("title","")}"\nIdentify the song.'}]
            if thumb: cmin.insert(0, thumb)
            ev = {"youtube_title": info.get("title", ""), "youtube_channel": info.get("uploader", ""),
                  "youtube_description": (info.get("description", "") or "")[:600],
                  "shazam_guess": {"artist": tr.get("subtitle"), "title": tr.get("title")}}
            cfus = [{"type": "text", "text": "Cross-check ALL evidence (incl. thumbnail) and decide the true "
                     "song.\n\n" + json.dumps(ev)}]
            if thumb: cfus.insert(0, thumb)

            with timed("llm-min-opus"):   ask(cmin, OPUS)
            with timed("llm-fusion-opus"): ask(cfus, OPUS)
            with timed("llm-min-haiku"):  ask(cmin, HAIKU)
        except Exception as e:
            print(f"  SKIP {label}: {str(e)[:60]}", file=sys.stderr)
            continue

    print("\n\n=== PER-STAGE TIMING (6 songs, serial) ===\n")
    order = ["download", "convert", "shazam", "musicbrainz",
             "llm-min-opus", "llm-fusion-opus", "llm-min-haiku"]
    tot = 0
    print(f"{'stage':<18} {'avg':>7} {'min':>7} {'max':>7}")
    print("-" * 44)
    for k in order:
        xs = STAGE.get(k, [0])
        a = sum(xs) / len(xs); tot += a
        print(f"{k:<18} {a:>6.1f}s {min(xs):>6.1f}s {max(xs):>6.1f}s")
    print("-" * 44)
    print(f"MusicBrainz calls total: {MB_CALLS[0]} ({MB_CALLS[0]/len(SONGS):.1f}/song)")
    core = sum(sum(STAGE.get(k, [0]))/len(STAGE.get(k, [1])) for k in
               ["download", "convert", "shazam", "musicbrainz", "llm-min-haiku"])
    print(f"\nSerial per-song (opus, both arms): ~{tot:.0f}s")
    print(f"Lean per-song (haiku-min only, no fusion): ~{core:.0f}s")


if __name__ == "__main__":
    asyncio.run(run())
