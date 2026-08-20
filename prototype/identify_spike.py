#!/usr/bin/env python3
"""
PROTOTYPE — throwaway. 15-song test. Key question this round:
    Does MusicBrainz (the Authority) beat Shazam's OWN album+art? Or can we skip it?

Columns per Track:
  shazam-id      : Shazam artist - title            (Identification)
  shazam-own     : Shazam's own album + art?        (can this BE the Authority?)
  mb-isrc        : MusicBrainz album via ISRC        (Authority option B)
  llm-min        : Resolver, title + thumbnail only
  llm-fusion     : Resolver, all evidence together

Run:  python3 prototype/identify_spike.py
Reads ANTHROPIC_API_KEY from .env (gitignored). No persistence. Delete when done.
"""
import asyncio, base64, glob, json, os, re, subprocess, sys, tempfile, time, urllib.request

import anthropic, musicbrainzngs
from dotenv import load_dotenv
from shazamio import Shazam

load_dotenv()
musicbrainzngs.set_useragent("muzik-prototype", "0.0", "armand.amores1@gmail.com")
llm = anthropic.Anthropic()

MODEL, EFFORT = "claude-opus-5", "medium"
IN_COST, OUT_COST = 5e-6, 25e-6
STUDIO_BADGES = {"compilation", "live", "remix", "dj-mix", "mixtape", "demo", "soundtrack"}
_cost = {"in": 0, "out": 0}

SONGS = [
    ("mainstream",   "Daft Punk Get Lucky ft Pharrell"),
    ("cover",        "Johnny Cash Hurt"),
    ("french",       "Stromae Alors on danse"),
    ("meme",         "Rick Astley Never Gonna Give You Up"),
    ("remix",        "Avicii Levels Skrillex remix"),
    ("deceptive",    "africa toto lyrics"),                 # expect a junk-titled lyric upload
    ("japanese",     "YOASOBI 夜に駆ける"),
    ("classical",    "Beethoven Moonlight Sonata 3rd movement"),
    ("live",         "Nirvana Where Did You Sleep Last Night Unplugged"),
    ("instrumental", "Deadmau5 Strobe"),
    ("feature",      "Kanye West Monster ft Nicki Minaj"),
    ("jazz-old",     "Frank Sinatra Fly Me to the Moon"),
    ("indie",        "Men I Trust Show Me How"),
    ("recent",       "Chappell Roan Pink Pony Club"),
    ("sped-up",      "Metro Boomin Creepin sped up"),       # edit; may have no clean album
]


# ---------- download + fingerprint ----------
def download(query, outdir):
    t0 = time.perf_counter()
    subprocess.run(
        ["yt-dlp", "-f", "bestaudio", "--no-playlist", "--write-info-json",
         "-o", os.path.join(outdir, "%(id)s.%(ext)s"),
         "--quiet", "--no-warnings", f"ytsearch1:{query}"], check=True)
    dl_sec = time.perf_counter() - t0        # search + media fetch = user-facing fetch time
    info = json.load(open(glob.glob(os.path.join(outdir, "*.info.json"))[0]))
    raw = next(p for p in glob.glob(os.path.join(outdir, "*")) if not p.endswith(".info.json"))
    mib = os.path.getsize(raw) / (1024 * 1024)
    wav = os.path.join(outdir, "clean.wav")
    subprocess.run(["ffmpeg", "-y", "-i", raw, "-ac", "1", "-ar", "16000", wav],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dur = info.get("duration") or 0
    timing = {"sec": dl_sec, "mib": mib,
              "mibps": mib / dl_sec if dl_sec else 0,
              "xrt": dur / dl_sec if dl_sec else 0}
    return wav, info, timing


def dig_meta(track, key):
    """Pull a labelled field (ISRC, Album, ...) from Shazam's section metadata."""
    if key.lower() == "isrc" and track.get("isrc"):
        return track["isrc"]
    for sec in track.get("sections", []):
        for md in sec.get("metadata", []) or []:
            if str(md.get("title", "")).lower() == key.lower():
                return md.get("text")
    return None


# ---------- MusicBrainz (Authority option B) ----------
_RGC = {}
def _rg(release_id):
    if release_id in _RGC:
        return _RGC[release_id]
    try:
        rg = musicbrainzngs.get_release_by_id(release_id, includes=["release-groups"])["release"].get("release-group", {})
    except Exception:
        rg = {}
    _RGC[release_id] = rg
    return rg


def mb_by_isrc(isrc):
    if not isrc:
        return "no ISRC"
    try:
        recs = musicbrainzngs.get_recordings_by_isrc(isrc, includes=["releases"])["isrc"]["recording-list"]
    except Exception as e:
        return f"MB err: {str(e)[:30]}"
    if not recs:
        return "no recording"
    best, best_date = None, "9999"
    for rel in recs[0].get("release-list", [])[:8]:
        rg = _rg(rel["id"])
        primary = (rg.get("primary-type") or rg.get("type") or "").lower()
        secondary = {s.lower() for s in rg.get("secondary-type-list", [])}
        if primary != "album" or (secondary & STUDIO_BADGES):
            continue
        date = rel.get("date", "9999") or "9999"
        if date < best_date:
            best, best_date = rel, date
    if best:
        return f"{best['title']} [studio]"
    rels = recs[0].get("release-list", [])
    return f"{rels[0]['title']} [other]" if rels else "no release"


# ---------- Resolver (LLM) ----------
def _thumb_block(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data, mt = r.read(), r.headers.get("Content-Type", "image/jpeg").split(";")[0]
    if mt not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        mt = "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": mt,
            "data": base64.standard_b64encode(data).decode()}}


def _ask(content):
    resp = llm.messages.create(
        model=MODEL, max_tokens=1500,
        thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
        system=("You identify the real recording behind a YouTube music video. Reply with ONLY a JSON "
                'object: {"artist": str, "title": str, "album": str|null, "confidence": 0-1, "note": str}. '
                "album = the studio album you would tag, or null if unsure. No prose outside the JSON."),
        messages=[{"role": "user", "content": content}])
    _cost["in"] += resp.usage.input_tokens
    _cost["out"] += resp.usage.output_tokens
    txt = next((b.text for b in resp.content if b.type == "text"), "{}")
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0) if m else txt)
    except Exception:
        return {"artist": "?", "title": "PARSE FAIL", "album": None, "confidence": 0}


def _fmt(d):
    return f'{d.get("artist")} - {d.get("title")} / {d.get("album")} (c={d.get("confidence")})'


def llm_minimal(info, thumb):
    c = [{"type": "text", "text": f'YouTube video title: "{info.get("title","")}"\nIdentify the song.'}]
    if thumb: c.insert(0, thumb)
    return _fmt(_ask(c))


def llm_fusion(info, shazam, thumb):
    ev = {"youtube_title": info.get("title", ""), "youtube_channel": info.get("uploader", ""),
          "youtube_description": (info.get("description", "") or "")[:600], "shazam_guess": shazam}
    c = [{"type": "text", "text": "Cross-check ALL of this evidence (including the thumbnail image) and "
          "decide the true song. If sources disagree, reason about which to trust.\n\n" + json.dumps(ev, indent=2)}]
    if thumb: c.insert(0, thumb)
    return _fmt(_ask(c))


# ---------- run ----------
async def run():
    shazam = Shazam()
    rows = []
    for label, query in SONGS:
        with tempfile.TemporaryDirectory() as d:
            print(f"[{label}] {query}", file=sys.stderr)
            row = {"case": label}
            try:
                audio, info, timing = download(query, d)
                row["yt"] = info.get("title", "")[:50]
                row["dl"] = f'{timing["sec"]:.1f}s  {timing["mib"]:.1f}MiB  {timing["mibps"]:.1f}MiB/s  {timing["xrt"]:.0f}x-realtime'
                row["_t"] = timing
            except Exception as e:
                row["err"] = f"DL FAIL {str(e)[:40]}"; rows.append(row); continue

            try:
                out = await shazam.recognize(audio)
            except AttributeError:
                out = await shazam.recognize_song(audio)
            except Exception as e:
                out = {}
            tr = out.get("track") or {}

            if tr:
                row["shazam"] = f'{tr.get("subtitle","?")} - {tr.get("title","?")}'
                sh_album = dig_meta(tr, "Album")
                sh_art = bool((tr.get("images") or {}).get("coverart"))
                row["shazam_own"] = f'{sh_album or "no album"} / art={"yes" if sh_art else "no"}'
                row["mb"] = mb_by_isrc(dig_meta(tr, "ISRC"))
            else:
                row["shazam"] = "NO MATCH -> Review queue"
                row["shazam_own"] = "-"; row["mb"] = "-"

            thumb = None
            if info.get("thumbnail"):
                try: thumb = _thumb_block(info["thumbnail"])
                except Exception: pass
            shazam_guess = {"artist": tr.get("subtitle"), "title": tr.get("title")}
            row["min"] = llm_minimal(info, thumb)
            row["fusion"] = llm_fusion(info, shazam_guess, thumb)
            rows.append(row)

    print("\n\n=== IDENTIFICATION SPIKE v3 (15 songs) ===")
    for r in rows:
        print(f"\n### {r['case']}   yt: {r.get('yt','?')}")
        if "err" in r:
            print("   ", r["err"]); continue
        print(f"   download   : {r['dl']}")
        print(f"   shazam-id  : {r['shazam']}")
        print(f"   shazam-own : {r['shazam_own']}")
        print(f"   mb-isrc    : {r['mb']}")
        print(f"   llm-min    : {r['min']}")
        print(f"   llm-fusion : {r['fusion']}")

    ts = [r["_t"] for r in rows if "_t" in r]
    if ts:
        avg = lambda k: sum(t[k] for t in ts) / len(ts)
        print(f"\n--- Download: avg {avg('sec'):.1f}s/song  {avg('mibps'):.1f}MiB/s  "
              f"{avg('xrt'):.0f}x-realtime  (n={len(ts)}, best {min(t['sec'] for t in ts):.1f}s, "
              f"worst {max(t['sec'] for t in ts):.1f}s) ---")
    cost = _cost["in"] * IN_COST + _cost["out"] * OUT_COST
    n = len([r for r in rows if "err" not in r])
    print(f"--- LLM: {_cost['in']} in + {_cost['out']} out tok = ${cost:.4f} over "
          f"{n} songs x 2 arms = ${cost/max(n,1):.4f}/song ({MODEL}, effort={EFFORT}) ---")


if __name__ == "__main__":
    asyncio.run(run())
