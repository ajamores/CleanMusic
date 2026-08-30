// REVIEW — clear the queue in one pass: listen, weigh the testimony, rule.

import { api, ApiError, audioUrl, coverUrl } from "../api.js";
import { el, clear } from "../dom.js";

export async function renderReview(view, { setBadge }) {
  const listBox = el("div");
  view.append(
    el("h1", { class: "view-title" }, "Review"),
    el("p", { class: "view-sub" },
      "Tracks whose Identification was too uncertain to auto-tag. Their Tags are provisional until you rule."),
    listBox,
  );

  async function load() {
    clear(listBox);
    let items;
    try {
      ({ items } = await api.review());
    } catch (err) {
      listBox.append(el("p", { class: "center-note" }, err.message));
      return;
    }
    setBadge(items.length);
    if (!items.length) {
      listBox.append(el("div", { class: "all-clear" },
        el("div", { class: "disc", "aria-hidden": "true" }),
        el("h2", {}, "Nothing awaits your ear"),
        el("p", {}, "Every Track passed the Confidence gate or has been ruled on. The queue is clear, sir."),
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

    const head = el("button", { class: "ri-head", type: "button", "aria-expanded": "false" },
      item.has_cover
        ? el("img", { class: "thumb", src: coverUrl(item.index), alt: "" })
        : el("span", { class: "thumb blank", "aria-hidden": "true" }, "♪"),
      el("span", { class: "ri-t" },
        el("span", { class: item.tags ? "ri-title" : "ri-title is-url" },
          item.tags ? `${item.tags.artist} — ${item.tags.title}` : item.source_url),
        el("span", { class: "ri-reason" }, item.reason),
      ),
      el("span", { class: "chev", "aria-hidden": "true" }, "›"),
    );
    head.addEventListener("click", () => {
      // Cover and audio are fetched lazily, on first open — a long queue
      // shouldn't hammer the server for media nobody has looked at yet.
      if (!built) { buildBody(body, item, li); built = true; }
      const open = body.hidden;
      body.hidden = !open;
      li.classList.toggle("open", open);
      head.setAttribute("aria-expanded", String(open));
    });

    li.append(head, body);
    return li;
  }

  // A blank field keeps its row but shows an em dash — an empty <dd> leaves a
  // hanging label that reads as a rendering fault, not an absent value.
  function dd(value) {
    return value
      ? el("dd", {}, value)
      : el("dd", { class: "empty" }, "—");
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
        "Provisional Tags — best-effort, drawn from the Source. Nothing is written as verified until you rule."));
  }

  function testimony(c) {
    return el("div", { class: "testimony" },
      el("h4", {}, "The Confidence gate could not reconcile the testimony"),
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
      ),
      el("p", { class: "why" }, el("b", {}, "The gate: "), c.why),
      c.witness_rationale ? el("blockquote", {}, c.witness_rationale) : null,
      c.witness_rationale ? el("p", { class: "attribution" }, "— the identity witness") : null,
    );
  }

  function buildBody(body, item, li) {
    const grid = el("div", { class: "ri-grid" },
      item.has_cover
        ? el("img", { class: "ri-cover", src: coverUrl(item.index), alt: "Provisional cover art" })
        : el("div", { class: "ri-cover blank", "aria-hidden": "true" }, "♪"),
      el("div", {},
        item.tags ? tagsBlock(item.tags) : el("p", { class: "provisional-note" }, "No provisional Tags."),
        item.has_audio
          ? el("div", { class: "ri-audio" },
              el("audio", { controls: true, preload: "none", src: audioUrl(item.index) }))
          : null,
      ),
    );

    const errorLine = el("p", { class: "decision-error", hidden: true });
    const panelBox = el("div", { class: "decision-panel", hidden: true });
    let openPanel = null;

    const buttons = {
      accept: el("button", { class: "btn-primary", type: "button" }, "Accept"),
      manual: el("button", { class: "btn-quiet", type: "button" }, "Manual"),
      hint: el("button", { class: "btn-quiet", type: "button" }, "Hint"),
      skip: el("button", { class: "btn-ghost", type: "button" }, "Skip"),
    };

    function busy(on) {
      for (const b of Object.values(buttons)) b.disabled = on;
    }

    async function decide(payload) {
      errorLine.hidden = true;
      busy(true);
      try {
        const res = await api.decide(item.index, { ...payload, source_url: item.source_url });
        if (res.cleared) {
          li.classList.add("clearing");
          await new Promise((r) => setTimeout(r, 320));
        } else {
          // Not cleared is a ruling, not a rewrite — the queue and its
          // indices are unchanged, so keep the card open with the reason.
          const reason = res.result && res.result.reason;
          errorLine.textContent = reason
            ? `Still unverified — ${reason}`
            : "Still unverified — it stays in the queue.";
          errorLine.hidden = false;
          busy(false);
          return;
        }
      } catch (err) {
        errorLine.textContent = err instanceof ApiError && err.status === 409
          ? `${err.message} — refreshing the queue.`
          : err.message;
        errorLine.hidden = false;
        if (!(err instanceof ApiError && err.status === 409)) { busy(false); return; }
        await new Promise((r) => setTimeout(r, 900));
      }
      // Indices shift after any queue rewrite — always re-fetch, never patch.
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
          labelled("Track №", f.track_number),
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
        type: "text", name: "hint", required: true,
        placeholder: "Artist - Title  (a nudge for another Identification pass)",
      });
      const form = el("form", {},
        el("div", { class: "tag-form" }, el("span", { class: "wide" }, input)),
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

    // Raw ParentNode.append stringifies null (unlike the el() helper) — append
    // the testimony only when there is a conflict to testify about.
    body.append(grid);
    if (item.conflict) body.append(testimony(item.conflict));
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
}
