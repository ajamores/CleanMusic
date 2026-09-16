// RUN: submit a Source, then watch the batch live over SSE.
// DESIGN.md 5.1. The SSE handling, the api.js calls and every id the QA
// driver and the mock depend on are the existing contract; what changed is
// the presentation: a scoreboard head, chips instead of dots, the live Track
// as a row, and progress on the shell's lower third rather than a local bar.

import { api, ApiError, openRunEvents } from "../api.js";
import { el, clear } from "../dom.js";

// The word is the rail's, not the view's (DESIGN.md 5.1): the Run view prints
// the detail line only, so the state is never spelled twice on one screen.
const STATE_WORD = {
  idle: "Idle",
  running: "Running",
  done: "Done",
  refused: "Refused",
  failed: "Failed",
};

// Scoreboard figures are zero-padded to two places. The number is the wire's;
// the padding is typography.
const pad2 = (n) => String(Math.max(0, Number(n) || 0)).padStart(2, "0");

const isVerified = (r) => r.status === "tagged" && !!(r.tags && r.tags.verified);

export async function renderRun(view, ctx) {
  const { setLamp, setBadge, setState, setSource, nowPlaying } = ctx;
  let es = null;
  let seen = 0;    // tracks already rendered, so a snapshot refresh doesn't duplicate
  let live = null; // the row for the Track currently downloading, if any
  let tally = { verified: 0, queued: 0, batch: 0 };

  async function refreshBadge() {
    // A finished run may have queued Tracks; the rail badge counts the queue,
    // so it is re-read at each terminal state rather than left stale.
    try { setBadge((await api.review()).items.length); } catch { /* convenience only */ }
  }

  // ---- head ----------------------------------------------------------------

  const figVerified = el("b", {}, "00");
  const figQueued = el("b", {}, "00");
  const figBatch = el("b", {}, "00");

  const head = el("header", { class: "view-head" },
    el("h1", {}, "Run"),
    el("span", { class: "rule", "aria-hidden": "true" }),
    el("div", { class: "scoreboard" },
      el("div", { class: "figure ok" }, figVerified, el("span", {}, "Verified")),
      el("div", { class: "figure review" }, figQueued, el("span", {}, "Queued")),
      el("div", { class: "figure" }, figBatch, el("span", {}, "In batch")),
    ),
  );

  // ---- form ----------------------------------------------------------------

  const urlInput = el("input", {
    type: "url", id: "src-url", required: true,
    placeholder: "Paste a YouTube Source, a video or a playlist",
    autocomplete: "off", spellcheck: "false",
  });
  const goBtn = el("button", { class: "btn-primary", type: "submit" }, "Run");
  const playlistToggle = el("input", { type: "checkbox", id: "opt-playlist" });
  const limitInput = el("input", { type: "number", id: "opt-limit", min: "1", placeholder: "all" });
  const formatSelect = el("select", { id: "opt-format" },
    el("option", { value: "m4a" }, "m4a"),
    el("option", { value: "mp3-320" }, "mp3 320"),
  );
  const concInput = el("input", { type: "number", id: "opt-conc", min: "1", max: "16", placeholder: "auto" });
  const formError = el("p", { class: "inline-error", hidden: true });

  // The label is always its own element above the control (DESIGN.md 3.2).
  const opt = (id, text, control) =>
    el("span", { class: "opt" }, el("label", { class: "field-label", for: id }, text), control);

  const form = el("form", { class: "run-form" },
    el("label", { class: "field-label", for: "src-url" }, "Source"),
    el("div", { class: "url-row" }, urlInput, goBtn),
    el("div", { class: "options-row" },
      el("label", { class: "switch", for: "opt-playlist" },
        playlistToggle, el("span", { class: "track" }), "Playlist"),
      opt("opt-limit", "Limit", limitInput),
      opt("opt-format", "Format", formatSelect),
      opt("opt-conc", "Concurrency", concInput),
    ),
    formError,
  );

  // ---- stage ---------------------------------------------------------------

  const stateLine = el("p", { class: "run-state-line", hidden: true });
  const listHead = el("div", { class: "list-head", hidden: true },
    el("span", { class: "legend" }, "Arrived"),
    el("span", { class: "rule", "aria-hidden": "true" }),
  );
  const tracklist = el("ul", { class: "tracklist" });
  // .summary-slot has no CSS of its own and wants none: it is a stable
  // clear() target so renderSummary can replace the plate without touching
  // its neighbours. Do not go hunting for a rule in run.css.
  const summaryBox = el("div", { class: "summary-slot" });
  const appendix = el("div", { class: "appendix" });
  const stage = el("section", { class: "stage" }, stateLine, listHead, tracklist, summaryBox, appendix);

  // ---- the idle screen -----------------------------------------------------

  // Before the first Source is pasted the stage is empty, and an empty stage
  // left the lower half of the work column bare. It carries the tracklist's
  // own empty state instead, and, standing on the bottom edge, the same teaching
  // block the Review view ends on: static copy, no count and no path the wire
  // has not supplied.
  const LEDGER = [
    ["Source", "Paste one video or a playlist above."],
    ["Download", "Each Track comes down as audio."],
    ["Match", "A fingerprint and the Authority name it."],
    ["Confidence gate", "Corroborated Tags are written into the file. The rest waits in the Review queue."],
  ];

  const idleScreen = el("section", { class: "run-idle", hidden: true },
    el("div", { class: "list-head" },
      el("span", { class: "legend" }, "Arrived"),
      el("span", { class: "rule", "aria-hidden": "true" }),
    ),
    el("p", { class: "idle-empty" },
      "Nothing has arrived yet. Each Track lands here as it is downloaded and ruled on."),
    el("div", { class: "run-ledger" },
      el("h2", {}, "How a run goes"),
      LEDGER.map(([term, def]) => [
        el("span", { class: "ledger-term" }, term),
        el("p", { class: "ledger-def" }, def),
      ]).flat(),
    ),
  );

  const sub = el("p", { class: "view-sub" },
    "One Source in, tagged Tracks out. Anything the Confidence gate cannot verify waits in Review, and the batch never blocks.");

  // .run-view keys every rule in run.css, so no Run rule can reach a shell
  // component in another view. It comes off again in the teardown.
  view.classList.add("run-view");
  view.append(head, sub, form, stage, idleScreen);

  // ---- reading order ---------------------------------------------------------

  // On a phone a run is watched far more often than it is started, so once one
  // has started the stage leads and the form drops below it. The nodes MOVE:
  // reordering the boxes with flex `order` would leave the visual sequence and
  // the DOM/tab sequence disagreeing (WCAG 1.3.2). Idle keeps the form first,
  // because there the form is the whole task.
  const mqPhone = window.matchMedia("(max-width: 900px)");
  let runState = "idle";

  function applyOrder() {
    const stageLeads = mqPhone.matches && runState !== "idle";
    const wanted = stageLeads
      ? [head, stage, form, sub, idleScreen]
      : [head, sub, form, stage, idleScreen];
    const now = view.children;
    if (wanted.every((node, i) => now[i] === node)) return;
    for (const node of wanted) view.append(node);
  }

  const onWidthChange = () => applyOrder();
  mqPhone.addEventListener("change", onWidthChange);

  // ---- rendering -----------------------------------------------------------

  // The wire's speed is yt-dlp's raw bytes/s (null between measurements);
  // formatting is the UI's side of the download-event contract (jobs.py).
  function fmtSpeed(bps) {
    if (typeof bps !== "number" || !isFinite(bps) || bps <= 0) return "";
    return bps >= 1048576
      ? `${(bps / 1048576).toFixed(1)}MiB/s`
      : `${Math.round(bps / 1024)}KiB/s`;
  }

  const clampPct = (p) => Math.max(0, Math.min(100, Number(p) || 0));

  function trackRow(result, animate, index = 0) {
    const t = result.tags;
    const verified = isVerified(result);
    const album = t ? [t.album, t.year].filter(Boolean).join(", ") : "";
    const li = el("li", {
      class: animate ? "arrive" : null,
      // Staggered arrival, capped: a batch snapshot never cascades for a second.
      style: animate && index ? `animation-delay: ${Math.min(index, 5) * 40}ms` : null,
    },
      el("span", { class: `chip ${verified ? "verified" : "review"}` }, verified ? "Verified" : "Review"),
      el("span", { class: "t-main" },
        el("span", { class: t ? "t-title" : "t-title is-url" }, t ? t.title : result.source_url),
        t && t.artist ? el("span", { class: "t-artist" }, ` ${t.artist}`) : null,
      ),
      album ? el("span", { class: "t-meta" }, album) : null,
      !verified && result.reason ? el("span", { class: "t-reason" }, result.reason) : null,
      // output_path is on the wire and the old UI threw it away: a verified
      // Track says where it was written.
      verified && result.output_path ? el("span", { class: "t-path" }, result.output_path) : null,
    );
    tracklist.append(li);
    listHead.hidden = false;
    tally.batch++;
    if (verified) tally.verified++; else tally.queued++;
  }

  // The downloading Track, drawn from the download event rather than invented:
  // it leaves the list the moment its real result arrives.
  function liveTrack(d) {
    if (!live) {
      const title = el("span", { class: "t-title" });
      const speed = el("span", { class: "t-meta t-speed" });
      const progress = el("span", { class: "t-progress" });
      const li = el("li", { class: "tk-live" },
        el("span", { class: "chip live" }, "Live"),
        el("span", { class: "t-main" }, title),
        speed, progress,
      );
      tracklist.append(li);
      live = { li, title, speed, progress };
    }
    // title is the Track's resolved YouTube title, the same one the CLI
    // announces; filename is an opaque %(id)s path, kept only as fallback.
    live.title.textContent = d.title || (d.filename || "").split("/").pop() || "";
    live.speed.textContent = fmtSpeed(d.speed);
    live.progress.textContent = `Downloading, ${Math.round(clampPct(d.percent))} per cent`;
    listHead.hidden = false;
  }

  function clearLive() {
    if (live) live.li.remove();
    live = null;
  }

  // The scoreboard counts what has actually landed, so it climbs with the run
  // rather than waiting for the summary. Every figure is the wire's own.
  function paintScore() {
    figVerified.textContent = pad2(tally.verified);
    figQueued.textContent = pad2(tally.queued);
    figBatch.textContent = pad2(tally.batch);
  }

  function renderSummary(state) {
    clear(summaryBox);
    if (!state.summary) return;
    summaryBox.append(el("div", { class: "run-summary" },
      el("div", { class: "figure ok" },
        el("b", {}, pad2(state.summary.verified)), el("span", {}, "Verified")),
      el("div", { class: "figure review" },
        el("b", {}, pad2(state.summary.queued)), el("span", {}, "Queued for review")),
      state.summary.queued
        ? el("a", { class: "btn-quiet to-review", href: "#/review" }, "Open review")
        : null,
    ));
  }

  function renderAppendix(state) {
    clear(appendix);
    if (state.skipped && state.skipped.length) {
      appendix.append(el("h3", {}, "Skipped"),
        el("ul", {}, state.skipped.map((s) =>
          el("li", {},
            el("span", { class: "ax-url" }, s.source_url),
            s.reason ? el("span", { class: "ax-note" }, s.reason) : null))));
    }
    if (state.archive_skips && state.archive_skips.length) {
      appendix.append(el("h3", {}, "Already in the download manifest"),
        el("ul", {}, state.archive_skips.map((u) =>
          el("li", {}, el("span", { class: "ax-url" }, u)))));
    }
    if (state.playlist_path) {
      appendix.append(el("h3", {}, "Playlist file"),
        el("ul", {}, el("li", {}, el("span", { class: "ax-url" }, state.playlist_path))));
    }
  }

  function renderState(state, { animateTracks = false } = {}) {
    const st = state.state;

    // The rail owns the word, the lamp and the Source line. One call each, from
    // the one place that knows the state.
    view.dataset.runState = st;
    runState = st;
    applyOrder();
    setState(STATE_WORD[st] || st, st);
    setSource(st === "idle" ? "" : (state.url || ""));
    setLamp(st === "running");
    if (st !== "running") { nowPlaying(null); clearLive(); }

    const bad = st === "failed" || st === "refused";
    stateLine.hidden = st === "idle";
    stateLine.className = `run-state-line is-${st}`;
    stateLine.textContent = bad ? (state.error || "") : (state.url || "");

    clear(tracklist);
    seen = 0;
    live = null;
    tally = { verified: 0, queued: 0, batch: 0 };
    for (const r of state.results || []) { trackRow(r, animateTracks, seen); seen++; }
    listHead.hidden = seen === 0;
    // The idle screen stands in for an empty stage, and only for an empty one:
    // if a previous batch's results are still on the wire, they are the screen.
    idleScreen.hidden = !(st === "idle" && seen === 0);
    if (state.summary) {
      // At a terminal state the run's own summary is the authority.
      tally.verified = state.summary.verified;
      tally.queued = state.summary.queued;
    }
    paintScore();
    renderSummary(state);
    renderAppendix(state);
    goBtn.disabled = st === "running";
  }

  // ---- SSE -----------------------------------------------------------------

  function attach() {
    if (es) es.close();
    es = openRunEvents({
      snapshot: (state) => renderState(state),
      download: (d) => {
        // The lower third is the progress meter (scaleX, never width).
        nowPlaying({ title: d.title || "", speed: fmtSpeed(d.speed), percent: clampPct(d.percent) });
        liveTrack(d);
      },
      track: (result) => { clearLive(); trackRow(result, true); seen++; paintScore(); },
      state: async ({ state }) => {
        if (state === "running") return;
        // Terminal "state" events carry only the word; the summary, skips
        // and playlist_path arrive by re-reading the full current state.
        if (es) { es.close(); es = null; }
        try { renderState(await api.currentRun()); } catch { /* keep what we have */ }
        refreshBadge();
      },
      onerror: () => { /* EventSource retries on its own; terminal close also lands here */ },
    });
  }

  // ---- submit --------------------------------------------------------------

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    formError.hidden = true;
    const body = {
      url: urlInput.value.trim(),
      playlist: playlistToggle.checked,
      limit: limitInput.value ? Number(limitInput.value) : null,
      format: formatSelect.value,
      concurrency: concInput.value ? Number(concInput.value) : null,
    };
    goBtn.disabled = true;
    try {
      const state = await api.startRun(body);
      renderState(state);
      if (state.state === "running") attach();
      else refreshBadge(); // a fast run can be terminal in the 202 itself
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // A run is already active: attach to it rather than complaining.
        try { renderState(await api.currentRun()); } catch {}
        attach();
      } else {
        formError.textContent = err.message;
        formError.hidden = false;
        goBtn.disabled = false;
      }
    }
  });

  // ---- mount ---------------------------------------------------------------

  try {
    const settings = await api.getSettings();
    formatSelect.value = settings.format;
  } catch { /* the select's default stands until the server answers */ }

  try {
    const state = await api.currentRun();
    renderState(state);
    if (state.state === "running") attach();
  } catch { /* an unreachable server surfaces on submit */ }

  return () => {
    if (es) es.close();
    mqPhone.removeEventListener("change", onWidthChange);
    // The view element belongs to the shell: Run leaves no mark on it, or the
    // next view inherits Run's state selectors.
    delete view.dataset.runState;
    view.classList.remove("run-view");
    clearLive();
    setLamp(false);
    setState("Idle", "idle");
    setSource("");
    nowPlaying(null);
  };
}
