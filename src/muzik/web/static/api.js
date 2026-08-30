// Thin client for API CONTRACT v1. Every function returns parsed JSON or
// throws ApiError carrying the HTTP status and the server's "error" message,
// so views can tell a 409 (busy / stale index) from a real failure.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new ApiError(0, "The player isn't answering. Is the server running?");
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok && res.status !== 202) {
    throw new ApiError(res.status, (body && body.error) || `Request failed (${res.status})`);
  }
  return body;
}

export const api = {
  startRun: (opts) => request("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  }),
  currentRun: () => request("/api/runs/current"),
  review: () => request("/api/review"),
  decide: (index, body) => request(`/api/review/${index}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  getSettings: () => request("/api/settings"),
  putSettings: (body) => request("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
};

// Media loads (<img src>, <audio src>) never pass through window.fetch, so
// the mock layer can't intercept them — it substitutes a URL factory instead.
export const audioUrl = (index) =>
  window.MuzikMediaUrl ? window.MuzikMediaUrl("audio", index) : `/api/review/${index}/audio`;
export const coverUrl = (index) =>
  window.MuzikMediaUrl ? window.MuzikMediaUrl("cover", index) : `/api/review/${index}/cover`;

// The mock layer (dev-mock.js) substitutes its own EventSource; real builds
// use the platform one. Named events per contract: snapshot, download,
// track, state. The stream closes itself after a terminal state.
export function openRunEvents(handlers) {
  const ES = window.MuzikEventSource || EventSource;
  const es = new ES("/api/runs/current/events");
  for (const [name, fn] of Object.entries(handlers)) {
    if (name === "onerror") es.onerror = fn;
    else es.addEventListener(name, (ev) => fn(JSON.parse(ev.data)));
  }
  return es;
}
