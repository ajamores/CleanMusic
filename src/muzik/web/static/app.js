// Shell: hash router, nav state, review badge, run lamp.

import { api } from "./api.js";
import { clear } from "./dom.js";
import { renderRun } from "./views/run.js";
import { renderReview } from "./views/review.js";
import { renderSettings } from "./views/settings.js";

const routes = {
  run: renderRun,
  review: renderReview,
  settings: renderSettings,
};

let teardown = null;

function currentRoute() {
  const name = (location.hash.replace(/^#\/?/, "") || "run").split("/")[0];
  return routes[name] ? name : "run";
}

async function navigate() {
  const name = currentRoute();
  for (const a of document.querySelectorAll(".nav a")) {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  // Views own live resources (the SSE stream, audio elements); each render
  // returns a teardown so navigating away closes them.
  if (teardown) { try { teardown(); } catch {} teardown = null; }
  const view = clear(document.getElementById("view"));
  teardown = await routes[name](view, { setBadge, setLamp }) || null;
}

export function setBadge(count) {
  const badge = document.getElementById("review-badge");
  badge.hidden = !count;
  badge.textContent = count || "";
}

export function setLamp(on) {
  document.getElementById("run-lamp").classList.toggle("on", on);
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
