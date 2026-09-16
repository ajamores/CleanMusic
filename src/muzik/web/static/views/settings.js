// SETTINGS (DESIGN.md 5.3). One knob: the download format, as two stacked
// plates rather than a dropdown, because it is a decision and not a preference.
// Under it, a plain account of how the pipeline thinks, in the domain's own
// words (CONTEXT.md), set as prose in two columns.

import { api } from "../api.js";
import { el } from "../dom.js";

const FORMATS = [
  {
    value: "m4a",
    name: "m4a",
    desc: "AAC as YouTube serves it. No re-encode, the cleanest copy available.",
  },
  {
    value: "mp3-320",
    name: "mp3 320",
    desc: "Re-encoded to MP3 at 320 kbps, for players that insist on it.",
  },
];

// A glossary word, spelled as CONTEXT.md spells it. Teal, not bold ink.
const g = (word) => el("span", { class: "g" }, word);
// The run-in lead of a paragraph: one step of the sequence, in plain ink.
const lead = (text) => el("b", { class: "lead" }, text);

export async function renderSettings(view) {
  // The head figure: the format currently in force. Hidden until the wire
  // tells us what it is, so nothing invents a value.
  const figureName = el("b", {});
  const scoreboard = el("div", { class: "scoreboard", hidden: true },
    el("div", { class: "figure ok" },
      figureName,
      el("span", {}, "Current format"),
    ),
  );

  const savedNote = el("span", { class: "settings-saved", role: "status" });
  const choice = el("div", {
    class: "format-choice",
    role: "radiogroup",
    "aria-label": "Download format",
  });
  const errorLine = el("p", { class: "inline-error", hidden: true });

  const plates = new Map();
  for (const f of FORMATS) {
    const radio = el("input", { type: "radio", name: "format", value: f.value });
    const state = el("span", { class: "fmt-state" }, "Select");
    const plate = el("label", { class: "fmt" },
      radio,
      el("i", { class: "fmt-box", "aria-hidden": "true" }),
      el("span", { class: "fmt-name" }, f.name),
      el("span", { class: "fmt-desc" }, f.desc),
      state,
    );
    radio.addEventListener("change", () => save(f.value));
    plates.set(f.value, { plate, radio, state, name: f.name });
    choice.append(plate);
  }

  // The format the server has confirmed. The head figure only ever shows this
  // one, so a failed write cannot leave the page claiming a format that is not
  // in force.
  let current = null;

  function reflect(format, pending = false) {
    for (const [value, { plate, radio, state }] of plates) {
      const on = value === format;
      radio.checked = on;
      plate.classList.toggle("selected", on);
      state.textContent = on ? (pending ? "Saving" : "Saved") : "Select";
    }
    if (pending) return;
    const chosen = plates.get(format);
    figureName.textContent = chosen ? chosen.name : "";
    scoreboard.hidden = !chosen;
  }

  let flashTimer = null;
  async function save(format) {
    errorLine.hidden = true;
    reflect(format, true);
    try {
      const settings = await api.putSettings({ format });
      current = settings.format;
      reflect(current);
      savedNote.textContent = "Saved.";
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => { savedNote.textContent = ""; }, 1800);
    } catch (err) {
      errorLine.textContent = err.message;
      errorLine.hidden = false;
      // Nothing was written, so the choice goes back to what is in force.
      if (current) reflect(current);
    }
  }

  const how = el("section", { class: "settings-block" },
    el("div", { class: "block-head" },
      el("h2", {}, "How this works"),
      el("i", { class: "rule", "aria-hidden": "true" }),
    ),
    el("div", { class: "how" },
      el("p", {},
        lead("A Source goes in."), " A YouTube URL, one video or a whole playlist. Each becomes one or more ",
        g("Tracks"), ": downloaded audio files, the unit of output."),
      el("p", {},
        lead("Each Track is identified."), " Acoustic fingerprinting proposes a ", g("Match"),
        ", a candidate identity. The ", g("Confidence gate"),
        " decides whether that Match is trustworthy enough to write as verified ", g("Tags"),
        ", checking it against the Source's own title. On the uncorroborated path it also consults the ",
        g("Resolver"), "'s ", g("Identity verdict"),
        ", an AI witness ruling on whether the Match fits the Track's own evidence."),
      el("p", {},
        lead("Verified Tags come from an Authority."), " Not one source but a waterfall: Shazam, then MusicBrainz, then the ",
        g("Resolver"), ", because each of them is unreliable alone."),
      el("p", {},
        lead("Anything uncertain waits in the Review queue."),
        " It gets provisional ", g("Tags"),
        ", never written as if confirmed, and the batch never blocks. You clear the queue in one pass: listen, weigh the testimony, rule."),
      el("p", {},
        lead("Playlist runs also write a playlist file."),
        " An .m3u8 beside the ", g("Tracks"),
        ", preserving the grouping, so a Track's album Tag stays its real album."),
    ),
  );

  view.append(
    el("div", { class: "view-head" },
      el("h1", {}, "Settings"),
      el("i", { class: "rule", "aria-hidden": "true" }),
      scoreboard,
    ),
    el("p", { class: "view-sub" }, "One knob, deliberately. Everything else is the pipeline's job."),
    el("section", { class: "settings-block" },
      el("div", { class: "block-head" },
        el("h2", {}, "Download format"),
        el("i", { class: "rule", "aria-hidden": "true" }),
        savedNote,
      ),
      choice,
      errorLine,
    ),
    how,
  );

  try {
    const settings = await api.getSettings();
    current = settings.format;
    reflect(current);
  } catch (err) {
    errorLine.textContent = err.message;
    errorLine.hidden = false;
  }

  return () => clearTimeout(flashTimer);
}
