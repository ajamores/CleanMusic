// Shell: hash router, nav state, the rail's on-air block, the lower third and
// the one equaliser. Views own their own DOM inside #view and nothing else;
// everything in the rail and the horizon is driven through the context object
// this module hands them (DESIGN.md 2.6).
//
// The rail is persistent chrome, so the run state it spells is the SHELL's, not
// the Run view's. A view may push a state into it (the Run view does, off its
// own stream), but when that view is torn down the shell re-primes the rail
// from /api/runs/current and, while a run is live, watches the run stream
// itself. Otherwise leaving #/run would leave the rail reading "Idle" one
// rail-width away from a Review queue that answers 409 because a run is active.

import { api, openRunEvents } from "./api.js";
import { clear } from "./dom.js";
import { mountEq } from "./eq.js";
import { renderRun } from "./views/run.js";
import { renderReview } from "./views/review.js";
import { renderSettings } from "./views/settings.js";

const routes = {
  run: renderRun,
  review: renderReview,
  settings: renderSettings,
};

const STATES = ["idle", "running", "done", "refused", "failed"];

const STATE_WORD = {
  idle: "Idle",
  running: "Running",
  done: "Done",
  refused: "Refused",
  failed: "Failed",
};

let teardown = null;
// navigate() is async and re-entrant: a second hash change can land while the
// first render is still awaiting its data. The generation token makes the last
// call the only winner, so a losing view can never install its teardown over
// the winner's and leave its EventSource open behind a live page.
let gen = 0;

// What the rail currently says, and what the lower third currently shows.
// Recorded on the way through the setters so a route change can carry a live
// run across the gap between one view's teardown and the shell's own re-prime,
// with no flash of "Idle" in between.
let rail = { word: "Idle", state: "idle", source: "" };
let lastDownload = null;

// The shell's own run stream. It exists only while no view owns one (that is,
// on every route except #/run) and only while a run is actually live, so there
// is never a second subscriber on the wire and never an idle connection.
let watch = null;

// One canvas for the whole app, mounted once at boot. Views never mount their
// own: three rAF loops would cost more than the whole rest of the page.
// Exported so QA can drive the shell contract without a view in the way; the
// views themselves always reach it through the context object.
export const eq = mountEq(document.querySelector(".horizon"));

function currentRoute() {
  const name = (location.hash.replace(/^#\/?/, "") || "run").split("/")[0];
  return routes[name] ? name : "run";
}

async function navigate() {
  const my = ++gen;
  const name = currentRoute();
  for (const a of document.querySelectorAll(".nav a")) {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  // A Review audio node must never survive a route change, so the analyser is
  // dropped before the outgoing view is torn down.
  eq.detach();
  closeWatch();
  // Carry the rail's reading across the teardown: a view's teardown resets the
  // shell's state (it cannot know whether the run outlives it), and the truth
  // arrives one fetch later.
  const carried = { ...rail, download: lastDownload };
  // Views own live resources (the SSE stream, audio elements); each render
  // returns a teardown so navigating away closes them.
  if (teardown) { try { teardown(); } catch {} teardown = null; }
  if (carried.state === "running") restoreRail(carried);
  else nowPlaying(null);
  const view = clear(document.getElementById("view"));
  view.classList.remove("view-enter");
  void view.offsetWidth;
  view.classList.add("view-enter");
  const t = await routes[name](view, { setBadge, setLamp, setState, setSource, nowPlaying, eq });
  if (my !== gen) {
    // A newer navigate() has already rendered and owns the page. This render
    // lost, so it tears itself down immediately instead of becoming the
    // recorded teardown and outliving its own DOM.
    try { if (t) t(); } catch {}
    return;
  }
  teardown = t || null;
  // #/run drives the rail off its own stream; every other route is the shell's
  // to keep honest.
  if (name !== "run") primeRail(my);
}

export function setBadge(count) {
  const badge = document.getElementById("review-badge");
  badge.hidden = !count;
  badge.textContent = count || "";
}

export function setLamp(on) {
  document.getElementById("run-lamp").classList.toggle("on", on);
}

// The state word lives in the rail and nowhere else. The Run view prints the
// detail line; it does not print the word twice.
export function setState(word, state) {
  const onair = document.getElementById("run-onair");
  document.getElementById("run-state").textContent = word || "Idle";
  for (const s of STATES) onair.classList.toggle(`is-${s}`, s === state);
  if (!STATES.includes(state)) onair.classList.add("is-idle");
  rail.word = word || "Idle";
  rail.state = STATES.includes(state) ? state : "idle";
}

export function setSource(text) {
  const line = document.getElementById("run-source");
  line.textContent = text || "";
  rail.source = text || "";
}

// The lower third. It also drives the equaliser level, so a view never has to
// keep the two in step by hand.
export function nowPlaying(data) {
  const plate = document.getElementById("now-downloading");
  lastDownload = data || null;
  if (!data) {
    plate.hidden = true;
    plate.querySelector(".lt-meter").style.transform = "scaleX(0)";
    eq.setLevel(0);
    return;
  }
  const pct = Math.max(0, Math.min(100, Number(data.percent) || 0));
  plate.hidden = false;
  plate.querySelector(".lt-title").textContent = data.title || "";
  const speed = plate.querySelector(".lt-speed");
  speed.textContent = data.speed || "";
  speed.hidden = !data.speed;
  plate.querySelector(".lt-pct b").textContent = String(Math.round(pct));
  // scaleX, never width: an animated width is a layout every frame.
  plate.querySelector(".lt-meter").style.transform = `scaleX(${pct / 100})`;
  eq.setLevel(pct / 100);
}

// ---- the shell's run state -------------------------------------------------

// The wire's speed is yt-dlp's raw bytes/s (null between measurements); the
// Run view formats its own copy the same way (views/run.js).
function fmtSpeed(bps) {
  if (typeof bps !== "number" || !isFinite(bps) || bps <= 0) return "";
  return bps >= 1048576
    ? `${(bps / 1048576).toFixed(1)}MiB/s`
    : `${Math.round(bps / 1024)}KiB/s`;
}

const clampPct = (p) => Math.max(0, Math.min(100, Number(p) || 0));

function restoreRail(carried) {
  setState(carried.word, carried.state);
  setSource(carried.source);
  setLamp(carried.state === "running");
  eq.setMode(carried.state);
  nowPlaying(carried.download);
}

// One state object from the wire, painted across every piece of shell chrome.
function applyRun(state) {
  const st = STATES.includes(state && state.state) ? state.state : "idle";
  setState(STATE_WORD[st], st);
  setSource(st === "idle" ? "" : (state.url || ""));
  setLamp(st === "running");
  eq.setMode(st);
  if (st !== "running") nowPlaying(null);
}

function closeWatch() {
  if (watch) { try { watch.close(); } catch {} watch = null; }
}

function openWatch(my) {
  closeWatch();
  watch = openRunEvents({
    snapshot: (state) => { if (my === gen) applyRun(state); },
    download: (d) => {
      if (my !== gen) return;
      nowPlaying({ title: d.title || "", speed: fmtSpeed(d.speed), percent: clampPct(d.percent) });
    },
    state: async ({ state }) => {
      if (state === "running") return;
      // Terminal "state" events carry only the word; the Source line and the
      // settled horizon come from re-reading the full current state.
      closeWatch();
      let full = null;
      try { full = await api.currentRun(); } catch { /* the word is enough */ }
      if (my !== gen) return;
      applyRun(full || { state });
      primeBadge(); // a finished run can have filled the queue while we watched
    },
    onerror: () => { /* EventSource retries on its own; terminal close lands here too */ },
  });
}

// Re-prime the rail from the server the way primeBadge() re-primes the badge,
// then keep watching if the run is still live.
async function primeRail(my) {
  let state;
  try { state = await api.currentRun(); } catch { return; }
  if (my !== gen) return;
  applyRun(state);
  if (state.state === "running") {
    if (lastDownload) nowPlaying(lastDownload);
    openWatch(my);
  }
}

async function primeBadge() {
  try {
    const { items } = await api.review();
    setBadge(items.length);
  } catch { /* badge is a convenience; the Review view reports real errors */ }
}

window.addEventListener("hashchange", navigate);
primeBadge();
navigate();
