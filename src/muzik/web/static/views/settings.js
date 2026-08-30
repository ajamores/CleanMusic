// SETTINGS — the download format, and a plain account of how the pipeline
// thinks, in the domain's own words (CONTEXT.md).

import { api } from "../api.js";
import { el, clear } from "../dom.js";

const FORMATS = [
  { value: "m4a", name: "m4a", desc: "AAC as YouTube serves it — no re-encode, the cleanest copy available." },
  { value: "mp3-320", name: "mp3 · 320", desc: "Re-encoded to MP3 at 320 kbps, for players that insist on it." },
];

export async function renderSettings(view) {
  const savedNote = el("span", { class: "settings-saved", role: "status" });
  const choice = el("div", { class: "format-choice", role: "radiogroup", "aria-label": "Download format" });
  const errorLine = el("p", { class: "inline-error", hidden: true });

  const labels = new Map();
  for (const f of FORMATS) {
    const radio = el("input", { type: "radio", name: "format", value: f.value });
    const label = el("label", {},
      radio,
      el("span", { class: "f-name" }, f.name),
      el("span", { class: "f-desc" }, f.desc),
    );
    radio.addEventListener("change", () => save(f.value));
    labels.set(f.value, { label, radio });
    choice.append(label);
  }

  function reflect(format) {
    for (const [value, { label, radio }] of labels) {
      radio.checked = value === format;
      label.classList.toggle("selected", value === format);
    }
  }

  let flashTimer = null;
  async function save(format) {
    errorLine.hidden = true;
    reflect(format);
    try {
      const settings = await api.putSettings({ format });
      reflect(settings.format);
      savedNote.textContent = "Saved.";
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => { savedNote.textContent = ""; }, 1800);
    } catch (err) {
      errorLine.textContent = err.message;
      errorLine.hidden = false;
    }
  }

  const how = el("div", { class: "settings-block how" },
    el("h2", {}, "How this works"),
    el("p", {}, el("b", {}, "A Source goes in."), " A YouTube URL — one video or a playlist. Each becomes one or more ",
      el("b", {}, "Tracks"), ": downloaded audio files, the unit of output."),
    el("p", {}, el("b", {}, "Each Track is identified."), " Acoustic fingerprinting proposes a ", el("b", {}, "Match"),
      " — a candidate identity. The ", el("b", {}, "Confidence gate"),
      " decides whether that Match is trustworthy enough to write as verified ", el("b", {}, "Tags"),
      ", checking it against the Source's own title; on the uncorroborated path it also consults the ",
      el("b", {}, "Resolver"), "'s ", el("b", {}, "Identity verdict"),
      " — an AI witness ruling on whether the Match fits the Track's own evidence."),
    el("p", {}, el("b", {}, "Verified Tags come from an Authority."), " Not one source but a waterfall — Shazam, then MusicBrainz, then the Resolver — because each is unreliable alone."),
    el("p", {}, el("b", {}, "Anything uncertain waits in the Review queue."),
      " It gets provisional Tags, never written as if confirmed, and the batch never blocks. You clear the queue in one pass: listen, weigh the testimony, rule."),
    el("p", {}, el("b", {}, "Playlist runs also write a playlist file"),
      " — an .m3u8 beside the Tracks preserving the grouping, so a Track's album Tag stays its real album."),
  );

  view.append(
    el("h1", { class: "view-title" }, "Settings"),
    el("p", { class: "view-sub" }, "One knob, deliberately. Everything else is the pipeline's job."),
    el("div", { class: "settings-block" },
      el("h2", {}, "Download format", savedNote),
      choice,
      errorLine,
    ),
    how,
  );

  try {
    const settings = await api.getSettings();
    reflect(settings.format);
  } catch (err) {
    errorLine.textContent = err.message;
    errorLine.hidden = false;
  }

  return () => clearTimeout(flashTimer);
}
