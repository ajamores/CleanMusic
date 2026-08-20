#!/usr/bin/env python3
"""
PROTOTYPE — throwaway. The OPTIMIZED pipeline, on local obscure tracks.
Measures real wall-clock with everything turned on:

  * concurrent across Tracks (semaphore)
  * Shazam = Identification + first album guess          (near-free)
  * MusicBrainz ONLY when Shazam's album looks non-canonical (single/EP/remix/missing)
  * Haiku Resolver ONLY when still unresolved            (text-only; no thumbnail for local files)

No download stage — these are already-local files. Ground truth = folder(artist)/file(title).
Run:  python3 prototype/optimized_pipeline.py
"""
import asyncio, difflib, glob, json, os, re, subprocess, tempfile, time

import anthropic, musicbrainzngs
from dotenv import load_dotenv
from shazamio import Shazam

load_dotenv()
musicbrainzngs.set_useragent("muzik-prototype", "0.0", "armand.amores1@gmail.com")
llm = anthropic.Anthropic()

HAIKU = "claude-haiku-4-5"
SEM = 8
STUDIO_BADGES = {"compilation", "live", "remix", "dj-mix", "mixtape", "demo", "soundtrack"}
NON_CANON = re.compile(r"\b(single|ep|remix|remixes|live|instrumental)\b", re.I)
MB_CALLS = [0]; LLM_CALLS = [0]

ROOT = "/mnt/c/Users/aj_am/Music/CleanMuzik"
PICKS = [
    "D Power Diesle/Sniper (feat. Skepta).mp3",
    "DJ Deckstream/Life Is Good (feat. Yasiin Bey).mp3",
    "Dave East/Moonwalking -  Throwback Thursday Studio Session.mp3",
    "Lute/Ballad of Westside Scoop.mp3",
    "Nemzzz/1 FLOW.mp3",
    "Odeal/Children of Yeshua.mp3",
    "Ogi/Envy.mp3",
    "Larry June & Cardo/Gas Station Run.mp3",
    "River Tiber/West (feat. Daniel Caesar).mp3",
    "Westside Gunn/Why I do em Like that (feat. Billie Essco).mp3",
]


def norm(s):
    s = re.sub(r"\(feat[^)]*\)|\[[^\]]*\]|feat\.?.*", "", s or "", flags=re.I)
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def convert(path, wav):
    subprocess.run(["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", "16000", "-t", "60", wav],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dig(track, key):
    if key.lower() == "isrc" and track.get("isrc"):
        return track["isrc"]
    for sec in track.get("sections", []):
        for md in sec.get("metadata", []) or []:
            if str(md.get("title", "")).lower() == key.lower():
                return md.get("text")
    return None


def mb_album(isrc):
    if not isrc:
        return None
    try:
        MB_CALLS[0] += 1
        recs = musicbrainzngs.get_recordings_by_isrc(isrc, includes=["releases"])["isrc"]["recording-list"]
        if not recs:
            return None
        MB_CALLS[0] += 1
        rels = musicbrainzngs.browse_releases(recording=recs[0]["id"], includes=["release-groups"], limit=100)["release-list"]
    except Exception:
        return None   # obscure tracks 404 in MB — expected, fall through to Resolver
    best, best_date = None, "9999"
    for rel in rels:
        rg = rel.get("release-group", {})
        primary = (rg.get("primary-type") or rg.get("type") or "").lower()
        secondary = {s.lower() for s in rg.get("secondary-type-list", [])}
        if primary != "album" or (secondary & STUDIO_BADGES):
            continue
        d = rel.get("date", "9999") or "9999"
        if d < best_date:
            best, best_date = rel, d
    return best["title"] if best else None


def haiku_album(artist, title):
    LLM_CALLS[0] += 1
    r = llm.messages.create(
        model=HAIKU, max_tokens=300,
        system=('Given an artist and song, reply with ONLY JSON {"album": str|null}. '
                "album = the studio album this song originally appeared on, or null if you are unsure. "
                "Do not guess wildly."),
        messages=[{"role": "user", "content": f"Artist: {artist}\nSong: {title}\nWhat studio album?"}])
    txt = next((b.text for b in r.content if b.type == "text"), "{}")
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0) if m else txt).get("album")
    except Exception:
        return None


async def process(shazam, relpath, sem):
    async with sem:
        t = {}
        gt_artist, gt_title = relpath.split("/")[0], os.path.splitext(os.path.basename(relpath))[0]
        path = os.path.join(ROOT, relpath)
        with tempfile.TemporaryDirectory() as d:
            wav = os.path.join(d, "c.wav")
            t0 = time.perf_counter()
            await asyncio.to_thread(convert, path, wav)
            t["convert"] = time.perf_counter() - t0

            t0 = time.perf_counter()
            try:
                out = await shazam.recognize(wav)
            except AttributeError:
                out = await shazam.recognize_song(wav)
            except Exception:
                out = {}
            t["shazam"] = time.perf_counter() - t0
            tr = out.get("track") or {}

        if not tr:
            return {"gt": f"{gt_artist} - {gt_title}", "id": "NO MATCH -> Review queue",
                    "album": "-", "src": "-", "t": t, "matched": False}

        sh_artist, sh_title = tr.get("subtitle", "?"), tr.get("title", "?")
        sh_album = dig(tr, "Album")
        album, src = sh_album, "shazam"

        if not sh_album or NON_CANON.search(sh_album):        # MB only when the album looks off
            t0 = time.perf_counter()
            mb = await asyncio.to_thread(mb_album, dig(tr, "ISRC"))
            t["mb"] = time.perf_counter() - t0
            if mb:
                album, src = mb, "musicbrainz"

        if not album or NON_CANON.search(album or ""):        # Resolver only if still unresolved
            t0 = time.perf_counter()
            res = await asyncio.to_thread(haiku_album, sh_artist, sh_title)
            t["resolver"] = time.perf_counter() - t0
            if res:
                album, src = res, "resolver"

        matched = difflib.SequenceMatcher(None, norm(gt_title), norm(sh_title)).ratio() > 0.6
        return {"gt": f"{gt_artist} - {gt_title}", "id": f"{sh_artist} - {sh_title}",
                "album": album or "none", "src": src, "t": t, "matched": matched}


async def run():
    shazam = Shazam()
    sem = asyncio.Semaphore(SEM)
    wall0 = time.perf_counter()
    raw = await asyncio.gather(*[process(shazam, p, sem) for p in PICKS], return_exceptions=True)
    wall = time.perf_counter() - wall0
    results = [r for r in raw if isinstance(r, dict)]
    for p, r in zip(PICKS, raw):
        if not isinstance(r, dict):
            print(f"  FAIL {p}: {str(r)[:60]}")

    print("\n=== OPTIMIZED PIPELINE — 10 obscure local tracks ===\n")
    hits = 0
    for r in results:
        ok = "OK " if r["matched"] else "?? "
        hits += r["matched"]
        print(f"{ok}{r['gt']}")
        print(f"     id     : {r['id']}")
        print(f"     album  : {r['album']}  (via {r['src']})")
    print(f"\n--- WALL CLOCK: {wall:.1f}s for {len(PICKS)} tracks concurrent (sem={SEM}) "
          f"= {wall/len(PICKS):.1f}s/track effective ---")
    print(f"--- ID matched filename: {hits}/{len(PICKS)} | MB calls: {MB_CALLS[0]} | Resolver calls: {LLM_CALLS[0]} ---")
    # serial-sum comparison
    stage_tot = {}
    for r in results:
        for k, v in r["t"].items():
            stage_tot[k] = stage_tot.get(k, 0) + v
    serial = sum(stage_tot.values())
    print(f"--- if run serially it'd be ~{serial:.0f}s; concurrency gave {serial/max(wall,0.1):.1f}x speedup ---")
    print(f"--- stage totals (summed across tracks): " +
          ", ".join(f"{k} {v:.1f}s" for k, v in sorted(stage_tot.items(), key=lambda x: -x[1])) + " ---")


if __name__ == "__main__":
    asyncio.run(run())
