// REVIEW: clear the queue in one pass. Listen, weigh the testimony, rule.
// Presentation per DESIGN.md 5.2. Behaviour is unchanged from the first build:
// bodies are built lazily on first open, every decision carries the index plus
// the source_url that guards it, and any queue rewrite forces a re-fetch.

import { api, ApiError, audioUrl, coverUrl } from "../api.js";
import { el, clear } from "../dom.js";

// The four rulings, printed at the foot of the view in both the populated and
// the empty state: the interface teaches itself without a tour.
const RULINGS = [
  ["Accept", "Write the provisional Tags as verified."],
  ["Manual", "Type the Tags yourself, then write them."],
  ["Hint", "Nudge another Identification pass."],
  ["Skip", "Leave the file untagged and move on."],
];

export async function renderReview(view, ctx) {
  const { setBadge, nowPlaying, setSource } = ctx;

  // Every <audio> this view mounts, so a route change or a reload can never
  // leave one playing.
  const players = new Set();
  // "Ruled tonight" is a client-side count of cleared decisions, reset by the
  // mount itself. The wire carries no such number and none is invented.
  let ruled = 0;

  const figQueue = el("b", {}, "0");
  const figRuled = el("b", {}, "0");
  const listBox = el("div", { class: "review-box" });

  view.append(
    el("div", { class: "view-head rv-head" },
      el("h1", {}, "Review"),
      el("span", { class: "rule", "aria-hidden": "true" }),
      el("div", { class: "scoreboard" },
        el("div", { class: "figure review" }, figQueue, el("span", {}, "In queue")),
        el("div", { class: "figure" }, figRuled, el("span", {}, "Ruled tonight")),
      ),
    ),
    el("p", { class: "view-sub rv-sub" },
      "Tracks whose Identification was too uncertain to auto-tag. Their Tags are provisional until you rule."),
    listBox,
    rulings(),
  );

  function rulings() {
    const box = el("section", { class: "rulings" }, el("h2", {}, "The four rulings"));
    for (const [term, meaning] of RULINGS) {
      box.append(
        el("span", { class: "ruling-term" }, term),
        el("p", { class: "ruling-def" }, meaning),
      );
    }
    return box;
  }

  function silence() {
    for (const a of players) { try { a.pause(); } catch { /* already gone */ } }
    players.clear();
  }

  function score(inQueue) {
    figQueue.textContent = String(inQueue);
    figRuled.textContent = String(ruled);
  }

  async function load() {
    silence();
    clear(listBox);
    let items;
    try {
      ({ items } = await api.review());
    } catch (err) {
      score(0);
      listBox.append(el("p", { class: "center-note", role: "status" }, err.message));
      return;
    }
    setBadge(items.length);
    score(items.length);
    if (!items.length) {
      listBox.append(el("div", { class: "all-clear" },
        el("img", {
          class: "all-clear-crest", src: "./assets/crest-white-480.png",
          alt: "", "aria-hidden": "true", width: "847", height: "817",
        }),
        el("div", { class: "all-clear-say" },
          el("h2", {}, "Nothing awaits your ear"),
          el("p", {}, "Every Track passed the Confidence gate or has been ruled on. The queue is clear, sir."),
          el("a", { class: "btn-quiet", href: "#/run" }, "Back to Run"),
        ),
      ));
      return;
    }
    const ul = el("ul", { class: "review-list" });
    for (const item of items) ul.append(reviewItem(item));
    listBox.append(ul);
  }

  function reviewItem(item) {
    const li = el("li", { class: "review-item" });
    const body = el("div", { class: "ri-body", hidden: true });
    let built = false;

    const title = item.tags
      ? el("span", { class: "ri-title" }, item.tags.title)
      : el("span", { class: "ri-title is-url" }, item.source_url);

    const head = el("button", { class: "ri-head", type: "button", "aria-expanded": "false" },
      item.has_cover
        ? el("img", { class: "thumb", src: coverUrl(item.index), alt: "" })
        : el("span", { class: "thumb blank", "aria-hidden": "true" }, "♪"),
      el("span", { class: "ri-t" },
        el("span", { class: "ri-line" },
          title,
          item.tags ? el("span", { class: "ri-artist" }, item.tags.artist) : null,
        ),
        el("span", { class: "ri-reason" }, item.reason),
      ),
      el("span", { class: "ri-mark", "aria-hidden": "true" },
        el("span", { class: "ri-pos" }, String(item.index + 1)),
        el("span", { class: "chev" }, "›"),
      ),
    );
    head.addEventListener("click", () => {
      // Cover and audio are fetched lazily, on first open: a long queue
      // shouldn't hammer the server for media nobody has looked at yet.
      if (!built) { buildBody(body, item, li); built = true; }
      const open = body.hidden;
      body.hidden = !open;
      li.classList.toggle("open", open);
      head.setAttribute("aria-expanded", String(open));
      // A closed row must not keep its own preview running into the analyser.
      if (!open) for (const a of body.querySelectorAll("audio")) a.pause();
      // Bring the head to the top of the work column so the whole open body,
      // evidence first, starts on screen. Instant, not smooth: this is a jump
      // to a task, not choreography.
      if (open) head.scrollIntoView({ block: "start", behavior: "auto" });
    });

    li.append(head, body);
    return li;
  }

  // A blank field keeps its row and says so in words. An empty <dd> leaves a
  // hanging label that reads as a rendering fault, not an absent value.
  function dd(value) {
    return value
      ? el("dd", {}, value)
      : el("dd", { class: "empty" }, "not given");
  }

  function tagsBlock(tags) {
    const dl = el("dl", {},
      el("dt", {}, "Title"), dd(tags.title),
      el("dt", {}, "Artist"), dd(tags.artist),
      el("dt", {}, "Album"), dd(tags.album),
    );
    if (tags.track_number != null) dl.append(el("dt", {}, "Track"), el("dd", {}, String(tags.track_number)));
    if (tags.year != null) dl.append(el("dt", {}, "Year"), el("dd", {}, String(tags.year)));
    return el("div", { class: "ri-tags" }, dl,
      el("p", { class: "provisional-note" },
        "Provisional Tags, best effort, drawn from the Source. Nothing is written as verified until you rule."));
  }

  function testimony(c) {
    return el("div", { class: "testimony" },
      el("h3", {}, "The Confidence gate could not reconcile the testimony"),
      el("div", { class: "sides" },
        el("div", { class: "side" },
          el("p", { class: "who" }, "What the fingerprint heard"),
          el("dl", {},
            el("dt", {}, "Title"), dd(c.heard.title),
            el("dt", {}, "Artist"), dd(c.heard.artist),
            el("dt", {}, "Album"), dd(c.heard.album),
          ),
        ),
        el("div", { class: "side" },
          el("p", { class: "who" }, "What the Source claims"),
          el("dl", {},
            el("dt", {}, "Artist"), dd(c.source_artist),
            el("dt", {}, "Uploader"), dd(c.uploader),
          ),
        ),
        el("div", { class: "side wide" },
          el("p", { class: "who" }, "What the gate ruled"),
          el("p", { class: "why" }, c.why),
          c.witness_rationale ? el("blockquote", {}, c.witness_rationale) : null,
          c.witness_rationale ? el("p", { class: "attribution" }, "The identity witness") : null,
        ),
      ),
    );
  }

  function buildBody(body, item, li) {
    const audio = item.has_audio
      ? el("audio", { controls: true, preload: "none", src: audioUrl(item.index) })
      : null;
    if (audio) players.add(audio);

    // The record column reads tag record then testimony, beside the sleeve
    // rather than under it: full width below the grid stranded the conflict
    // off the fold and left the column half empty. See review.css.
    const grid = el("div", { class: "ri-grid" },
      el("div", { class: "ri-listen" },
        item.has_cover
          ? el("img", { class: "ri-cover", src: coverUrl(item.index), alt: "Provisional cover art" })
          : el("div", { class: "ri-cover blank", "aria-hidden": "true" }, "♪"),
        audio ? el("div", { class: "ri-audio" }, audio) : null,
      ),
      el("div", { class: "ri-record" },
        item.tags
          ? tagsBlock(item.tags)
          : el("p", { class: "provisional-note" },
              "No provisional Tags. There is nothing to accept, so rule with Manual, Hint or Skip."),
        item.conflict ? testimony(item.conflict) : null,
      ),
    );

    // The error text is the only feedback a failed ruling gives, so it is a
    // live region: unhiding it announces it.
    const errorLine = el("p", {
      class: "decision-error inline-error", role: "alert", hidden: true,
    });
    const panelBox = el("div", { class: "decision-panel", hidden: true });
    let openPanel = null;

    const buttons = {
      accept: el("button", { class: "btn-primary d-accept", type: "button" }, "Accept"),
      manual: el("button", { class: "btn-quiet d-manual", type: "button" }, "Manual"),
      hint: el("button", { class: "btn-quiet d-hint", type: "button" }, "Hint"),
      skip: el("button", { class: "btn-ghost d-skip", type: "button" }, "Skip"),
    };

    // Accept writes the provisional Tags as verified, so an entry that has
    // none can never be accepted: the engine answers 400 and the ruling is a
    // dead end. Offer the three rulings that do apply and nothing else.
    const canAccept = Boolean(item.tags);
    buttons.accept.disabled = !canAccept;

    function busy(on) {
      for (const b of Object.values(buttons)) b.disabled = on;
      buttons.accept.disabled = on || !canAccept;
    }

    async function decide(payload) {
      errorLine.hidden = true;
      busy(true);
      try {
        const res = await api.decide(item.index, { ...payload, source_url: item.source_url });
        if (res.cleared) {
          ruled += 1;
          li.classList.add("clearing");
          await new Promise((r) => setTimeout(r, 320));
        } else {
          // Not cleared is a ruling, not a rewrite: the queue and its indices
          // are unchanged, so keep the card open with the reason.
          const reason = res.result && res.result.reason;
          errorLine.textContent = reason
            ? `Still unverified. ${reason}`
            : "Still unverified. It stays in the queue.";
          errorLine.hidden = false;
          busy(false);
          return;
        }
      } catch (err) {
        errorLine.textContent = err instanceof ApiError && err.status === 409
          ? `${err.message} Refreshing the queue.`
          : err.message;
        errorLine.hidden = false;
        if (!(err instanceof ApiError && err.status === 409)) { busy(false); return; }
        await new Promise((r) => setTimeout(r, 900));
      }
      // Indices shift after any queue rewrite: always re-fetch, never patch.
      load();
    }

    buttons.accept.addEventListener("click", () => decide({ action: "accept" }));
    buttons.skip.addEventListener("click", () => decide({ action: "skip" }));

    function togglePanel(name, build) {
      if (openPanel === name) {
        panelBox.hidden = true;
        openPanel = null;
        return;
      }
      clear(panelBox);
      panelBox.append(build());
      panelBox.hidden = false;
      openPanel = name;
      panelBox.scrollIntoView({ block: "start", behavior: "auto" });
    }

    buttons.manual.addEventListener("click", () => togglePanel("manual", () => {
      const t = item.tags || {};
      const f = {
        title: el("input", { type: "text", name: "title", value: t.title || "", required: true }),
        artist: el("input", { type: "text", name: "artist", value: t.artist || "", required: true }),
        album: el("input", { type: "text", name: "album", value: t.album || "", required: true }),
        track_number: el("input", { type: "number", name: "track_number", min: "1", value: t.track_number ?? "" }),
        year: el("input", { type: "number", name: "year", min: "1900", max: "2100", value: t.year ?? "" }),
      };
      const form = el("form", {},
        el("div", { class: "tag-form" },
          labelled("Title", f.title, "wide"),
          labelled("Artist", f.artist),
          labelled("Album", f.album),
          labelled("Track number", f.track_number),
          labelled("Year", f.year),
        ),
        el("div", { class: "panel-actions" },
          el("button", { class: "btn-primary", type: "submit" }, "Write these Tags"),
          el("button", { class: "btn-ghost", type: "button", onclick: () => togglePanel("manual") }, "Cancel"),
        ),
      );
      form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const tags = {
          title: f.title.value.trim(),
          artist: f.artist.value.trim(),
          album: f.album.value.trim(),
        };
        if (f.track_number.value) tags.track_number = Number(f.track_number.value);
        if (f.year.value) tags.year = Number(f.year.value);
        decide({ action: "manual", tags });
      });
      return form;
    }));

    buttons.hint.addEventListener("click", () => togglePanel("hint", () => {
      const input = el("input", {
        type: "text", name: "hint", required: true, placeholder: "Artist - Title",
      });
      const form = el("form", {},
        el("div", { class: "tag-form" }, labelled("A nudge for another Identification pass", input, "wide")),
        el("div", { class: "panel-actions" },
          el("button", { class: "btn-primary", type: "submit" }, "Identify again"),
          el("button", { class: "btn-ghost", type: "button", onclick: () => togglePanel("hint") }, "Cancel"),
        ),
      );
      form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        decide({ action: "hint", hint: input.value.trim() });
      });
      setTimeout(() => input.focus(), 0);
      return form;
    }));

    body.append(grid);
    // The note sits above the bar rather than inside it: a wrapped mono path
    // between the rulings would push Skip off a phone screen.
    if (item.output_path) {
      body.append(el("p", { class: "writes-note" }, `Writes Tags to ${item.output_path}`));
    }
    body.append(
      el("div", { class: "decision-bar" },
        buttons.accept, buttons.manual, buttons.hint,
        el("span", { class: "spacer" }), buttons.skip),
      panelBox,
      errorLine,
    );
  }

  function labelled(text, input, extra) {
    return el("label", { class: extra || null },
      el("span", { class: "field-label" }, text), input);
  }

  await load();

  return () => {
    silence();
    nowPlaying(null);
    setSource("");
  };
}
