// RUN — submit a Source, then watch the batch live over SSE.

import { api, ApiError, openRunEvents } from "../api.js";
import { el, clear } from "../dom.js";

const STATE_COPY = {
  idle: "Idle",
  running: "Listening…",
  done: "Done",
  refused: "Refused",
  failed: "Failed",
};

export async function renderRun(view, { setLamp, setBadge }) {
  let es = null;
  let seen = 0; // tracks already rendered, so a snapshot refresh doesn't duplicate

  async function refreshBadge() {
    // A finished run may have queued Tracks; the header badge counts the
    // queue, so it is re-read at each terminal state rather than left stale.
    try { setBadge((await api.review()).items.length); } catch { /* convenience only */ }
  }

  // ---- form ----------------------------------------------------------------

  const urlInput = el("input", {
    type: "url", id: "src-url", required: true,
    placeholder: "Paste a YouTube Source — a video or a playlist",
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

  const form = el("form", { class: "run-form" },
    el("div", { class: "url-row" }, urlInput, goBtn),
    el("div", { class: "options-row" },
      el("label", { class: "switch", for: "opt-playlist" },
        playlistToggle, el("span", { class: "track" }), "Playlist"),
      el("span", { class: "opt" }, el("label", { for: "opt-limit" }, "Limit"), limitInput),
      el("span", { class: "opt" }, el("label", { for: "opt-format" }, "Format"), formatSelect),
      el("span", { class: "opt" }, el("label", { for: "opt-conc" }, "Concurrency"), concInput),
    ),
    formError,
  );

  // ---- stage ---------------------------------------------------------------

  const stateWord = el("span", { class: "state-word" });
  const stateUrl = el("span", { class: "state-url" });
  const stateLine = el("p", { class: "run-state-line", hidden: true }, stateWord, stateUrl);

  const npName = el("span", { class: "np-name" });
  const npSpeed = el("span", { class: "np-speed" });
  const npBar = el("i");
  const nowPlaying = el("div", { class: "now-playing", hidden: true },
    npName, npSpeed, el("div", { class: "meter" }, npBar));

  const tracklist = el("ul", { class: "tracklist" });
  const summaryBox = el("div");
  const appendix = el("div", { class: "appendix" });
  const stage = el("section", { class: "stage" }, stateLine, nowPlaying, tracklist, summaryBox, appendix);

  view.append(
    el("h1", { class: "view-title" }, "Run"),
    el("p", { class: "view-sub" },
      "One Source in, tagged Tracks out. Anything the Confidence gate can’t verify waits in Review — the batch never blocks."),
    form, stage,
  );

  // ---- rendering -----------------------------------------------------------

  // The wire's speed is yt-dlp's raw bytes/s (null between measurements) —
  // formatting is the UI's side of the download-event contract (jobs.py).
  function fmtSpeed(bps) {
    if (typeof bps !== "number" || !isFinite(bps) || bps <= 0) return "";
    return bps >= 1048576
      ? `${(bps / 1048576).toFixed(1)}MiB/s`
      : `${Math.round(bps / 1024)}KiB/s`;
  }

  function trackRow(result, animate) {
    const t = result.tags;
    const verified = result.status === "tagged" && t && t.verified;
    const li = el("li", { class: animate ? "arrive" : null },
      el("span", { class: `dot ${verified ? "ok" : "rev"}`, "aria-hidden": "true" }),
      el("span", { class: "t-main" },
        el("span", { class: t ? "t-title" : "t-title is-url" }, t ? t.title : result.source_url),
        t ? el("span", { class: "t-artist" }, ` — ${t.artist}`) : null,
      ),
      el("span", { class: `t-status ${verified ? "verified" : ""}` },
        verified ? "Verified" : "→ Review"),
      !verified && result.reason ? el("span", { class: "t-reason" }, result.reason) : null,
    );
    tracklist.append(li);
  }

  function renderSummary(state) {
    clear(summaryBox);
    if (!state.summary) return;
    summaryBox.append(el("div", { class: "run-summary" },
      el("div", { class: "verified" }, el("b", {}, String(state.summary.verified)), el("span", {}, "verified")),
      el("div", { class: "queued" }, el("b", {}, String(state.summary.queued)), el("span", {}, "queued for review")),
      state.summary.queued
        ? el("a", { class: "btn-quiet to-review", href: "#/review", role: "button" }, "Open Review")
        : null,
    ));
  }

  function renderAppendix(state) {
    clear(appendix);
    if (state.skipped && state.skipped.length) {
      appendix.append(el("h3", {}, "Skipped"),
        el("ul", {}, state.skipped.map((s) =>
          el("li", {}, s.source_url, " ", el("span", { class: "reason" }, `— ${s.reason}`)))));
    }
    if (state.archive_skips && state.archive_skips.length) {
      appendix.append(el("h3", {}, "Already in the download manifest"),
        el("ul", {}, state.archive_skips.map((u) => el("li", {}, u))));
    }
    if (state.playlist_path) {
      appendix.append(el("h3", {}, "Playlist file"),
        el("p", {}, el("code", {}, state.playlist_path)));
    }
  }

  function renderState(state, { animateTracks = false } = {}) {
    stateLine.hidden = state.state === "idle";
    stateLine.className = `run-state-line is-${state.state}`;
    stateWord.textContent = STATE_COPY[state.state] || state.state;
    stateUrl.textContent = state.state === "failed" || state.state === "refused"
      ? (state.error || "")
      : (state.url || "");
    setLamp(state.state === "running");
    if (state.state !== "running") nowPlaying.hidden = true;

    clear(tracklist);
    seen = 0;
    for (const r of state.results || []) { trackRow(r, animateTracks); seen++; }
    renderSummary(state);
    renderAppendix(state);
    goBtn.disabled = state.state === "running";
  }

  // ---- SSE -----------------------------------------------------------------

  function attach() {
    if (es) es.close();
    es = openRunEvents({
      snapshot: (state) => renderState(state),
      download: (d) => {
        nowPlaying.hidden = false;
        // title is the Track's resolved YouTube title — the same one the CLI
        // announces; filename is an opaque %(id)s path, kept only as fallback.
        npName.textContent = d.title || (d.filename || "").split("/").pop() || "";
        npSpeed.textContent = fmtSpeed(d.speed);
        npBar.style.width = `${Math.max(0, Math.min(100, d.percent || 0))}%`;
      },
      track: (result) => { trackRow(result, true); seen++; },
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
        // A run is already active — attach to it rather than complaining.
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
    if (state.state !== "idle") renderState(state);
    if (state.state === "running") attach();
  } catch { /* an unreachable server surfaces on submit */ }

  return () => { if (es) es.close(); setLamp(false); };
}
