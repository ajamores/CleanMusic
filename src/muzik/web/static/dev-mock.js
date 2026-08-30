// dev-mock — contract-shaped fixtures behind window.fetch, plus a fake
// EventSource, so every view renders with no backend. Opt-in via ?mock=1;
// never loaded otherwise (see the import gate in index.html). Shapes here
// mirror API CONTRACT v1 exactly — if the contract moves, move this file.

// ---------------------------------------------------------------------------
// fixtures

const TRACKS = [
  {
    source_url: "https://youtu.be/mock-01",
    status: "tagged", reason: null,
    output_path: "/music/Sade - Smooth Operator.m4a",
    tags: { title: "Smooth Operator", artist: "Sade", album: "Diamond Life", track_number: 4, year: 1984, verified: true },
    conflict: null,
  },
  {
    source_url: "https://youtu.be/mock-02",
    status: "tagged", reason: null,
    output_path: "/music/D'Angelo - Untitled (How Does It Feel).m4a",
    tags: { title: "Untitled (How Does It Feel)", artist: "D'Angelo", album: "Voodoo", track_number: 12, year: 2000, verified: true },
    conflict: null,
  },
  {
    source_url: "https://youtu.be/mock-03",
    status: "review", reason: "Match not corroborated by the Source's title",
    output_path: "/music/review/mock-03.m4a",
    tags: { title: "Trouble Man", artist: "Marvin Gaye", album: "Trouble Man", track_number: 1, year: 1972, verified: false },
    conflict: null,
  },
  {
    source_url: "https://youtu.be/mock-04",
    status: "review", reason: "Identity verdict: inconsistent",
    output_path: "/music/review/mock-04.m4a",
    tags: { title: "Where I Wanna Be", artist: "Donell Jones", album: "Where I Wanna Be", track_number: null, year: 1999, verified: false },
    conflict: {
      heard: { title: "Where I Wanna Be", artist: "Donell Jones", album: "Where I Wanna Be" },
      source_artist: "D. Jones",
      uploader: "ThrowbackRnB Uploads",
      why: "The Source's title carries no independent artist witness, and the uploader is not the artist's channel.",
      witness_rationale: "The fingerprint names Donell Jones, but the upload is a fan re-post: the channel has no artist affiliation, the description credits a compilation, and the thumbnail text names the album rather than this recording. The evidence does not corroborate the Match.",
    },
  },
  {
    source_url: "https://youtu.be/mock-05",
    status: "review", reason: "No Match — fingerprint came back empty",
    output_path: null,
    tags: null,
    conflict: null,
  },
];

const SKIPPED = [
  { source_url: "https://youtu.be/mock-90", reason: "members-only video" },
];
const ARCHIVE_SKIPS = ["https://youtu.be/mock-91", "https://youtu.be/mock-92"];

let settings = { format: "m4a" };

// The Review queue: review-bound fixtures, cleared by decisions.
let queue = TRACKS.filter((t) => t.status === "review").map((t) => ({ ...t }));

const run = {
  state: "idle", url: null, results: [], skipped: [], archive_skips: [],
  playlist_path: null, summary: null, error: null,
};

function runSnapshot() {
  return JSON.parse(JSON.stringify(run));
}

function reviewItems() {
  return queue.map((t, index) => ({
    index,
    source_url: t.source_url,
    reason: t.reason,
    tags: t.tags,
    output_path: t.output_path,
    conflict: t.conflict,
    has_audio: !!t.output_path,
    has_cover: !!t.tags,
  }));
}

// ---------------------------------------------------------------------------
// generated media — a drawn cover and a short rendered chord, so the player
// and artwork are exercised offline with zero binary fixtures.

function makeCover(index) {
  const c = document.createElement("canvas");
  c.width = c.height = 320;
  const g = c.getContext("2d");
  const hues = [200, 16, 262, 140, 40];
  const hue = hues[index % hues.length];
  const grad = g.createLinearGradient(0, 0, 320, 320);
  grad.addColorStop(0, `oklch(45% 0.1 ${hue})`);
  grad.addColorStop(1, `oklch(22% 0.06 ${hue + 40})`);
  g.fillStyle = grad;
  g.fillRect(0, 0, 320, 320);
  g.strokeStyle = "oklch(90% 0.02 " + hue + " / 0.5)";
  for (let r = 30; r < 160; r += 14) {
    g.beginPath(); g.arc(160, 160, r, 0, Math.PI * 2); g.stroke();
  }
  g.fillStyle = "oklch(95% 0.01 90)";
  g.font = "700 28px system-ui";
  g.fillText("MOCK COVER", 78, 168);
  return c.toDataURL("image/jpeg", 0.9);
}

function makeWav() {
  const rate = 22050, seconds = 3, n = rate * seconds;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const fade = Math.min(1, t * 8) * Math.exp(-t * 0.9);
    const s = (Math.sin(2 * Math.PI * 220 * t) + Math.sin(2 * Math.PI * 277.2 * t) + Math.sin(2 * Math.PI * 329.6 * t)) / 3;
    v.setInt16(44 + i * 2, s * fade * 0x5fff, true);
  }
  return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
}

const covers = new Map();
let wavUrl = null;
window.MuzikMediaUrl = (kind, index) => {
  if (kind === "cover") {
    if (!covers.has(index)) covers.set(index, makeCover(index));
    return covers.get(index);
  }
  return (wavUrl ??= makeWav());
};

// ---------------------------------------------------------------------------
// fake SSE — one live stream at a time, driven by the run timeline below.

let liveStream = null;

class MockEventSource {
  constructor() {
    this.listeners = new Map();
    this.onerror = null;
    liveStream = this;
    // Contract: "snapshot" arrives immediately on connect.
    setTimeout(() => this.emit("snapshot", runSnapshot()), 10);
  }
  addEventListener(name, fn) {
    (this.listeners.get(name) || this.listeners.set(name, []).get(name)).push(fn);
  }
  emit(name, data) {
    for (const fn of this.listeners.get(name) || []) {
      fn({ data: JSON.stringify(data) });
    }
  }
  close() { if (liveStream === this) liveStream = null; }
}
window.MuzikEventSource = MockEventSource;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function playTimeline() {
  const perTrack = 1400;
  for (const track of TRACKS) {
    if (run.state !== "running") return; // a new run reset us — stop narrating
    const name = (track.output_path || track.source_url).split("/").pop();
    for (let pct = 0; pct <= 100; pct += 25) {
      // The real wire's semantics (jobs.py): filename is yt-dlp's opaque
      // %(id)s path, speed a raw bytes/s float, title the resolved YouTube
      // title. The SPA does the formatting — the mock must not.
      liveStream?.emit("download", {
        filename: `downloads/mock-${TRACKS.indexOf(track)}.m4a.part`, percent: pct,
        speed: (1.2 + Math.random() * 2.4) * 1048576,
        title: track.tags ? `${track.tags.artist} - ${track.tags.title}` : name,
      });
      await sleep(perTrack / 5);
    }
    run.results.push(track);
    liveStream?.emit("track", track);
  }
  run.state = "done";
  run.skipped = SKIPPED;
  run.archive_skips = ARCHIVE_SKIPS;
  run.playlist_path = run.playlist ? "/music/2026-08 - Liked from August.m3u8" : null;
  run.summary = {
    verified: TRACKS.filter((t) => t.status === "tagged").length,
    queued: TRACKS.filter((t) => t.status === "review").length,
  };
  liveStream?.emit("state", { state: "done" });
}

// ---------------------------------------------------------------------------
// fetch intercept

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const realFetch = window.fetch.bind(window);

window.fetch = async (input, options = {}) => {
  const path = typeof input === "string" ? input : input.url;
  if (!path.startsWith("/api/")) return realFetch(input, options);
  await sleep(120); // a hint of latency, so loading states are honest

  if (path === "/api/settings") {
    if (options.method === "PUT") settings = JSON.parse(options.body);
    return json(settings);
  }

  if (path === "/api/runs" && options.method === "POST") {
    if (run.state === "running") return json({ error: "A run is already active." }, 409);
    const req = JSON.parse(options.body);
    if (!req.playlist && /list=/.test(req.url)) {
      Object.assign(run, {
        state: "refused", url: req.url, results: [], skipped: [], archive_skips: [],
        playlist_path: null, summary: null,
        error: "That Source is a bare playlist. Re-run with the playlist option to fetch it as one.",
      });
      return json(runSnapshot(), 202);
    }
    Object.assign(run, {
      state: "running", url: req.url, playlist: req.playlist, results: [],
      skipped: [], archive_skips: [], playlist_path: null, summary: null, error: null,
    });
    playTimeline();
    return json(runSnapshot(), 202);
  }

  if (path === "/api/runs/current") return json(runSnapshot());

  if (path === "/api/review") return json({ items: reviewItems() });

  const decision = path.match(/^\/api\/review\/(\d+)\/decision$/);
  if (decision && options.method === "POST") {
    if (run.state === "running") return json({ error: "A run is active — the Review queue is read-only until it finishes." }, 409);
    const index = Number(decision[1]);
    const req = JSON.parse(options.body);
    const item = queue[index];
    if (!item || item.source_url !== req.source_url) {
      return json({ error: "The queue changed under you — that index is stale." }, 409);
    }
    if (req.action === "hint" && !/-/.test(req.hint || "")) {
      // Demonstrates the not-cleared path: a hint that re-identifies but
      // still fails the Confidence gate keeps the Track queued.
      return json({ cleared: false, result: { ...item, reason: "Hint re-identified, but the Match still failed the Confidence gate" } });
    }
    queue.splice(index, 1);
    return json({ cleared: true, result: { ...item, status: "tagged" } });
  }

  return json({ error: `mock: no route for ${options.method || "GET"} ${path}` }, 404);
};

console.info("[muzik] mock layer active — fixtures only, no backend");
