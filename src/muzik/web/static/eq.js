// The equaliser horizon: one canvas for the whole app, mounted once by app.js
// and driven by the views through the context object. DESIGN.md section 6.
//
// It is decoration (aria-hidden, pointer-events: none) and it sits in its own
// grid row, so nothing is ever drawn over text. The loop reads no layout,
// clears once and fills N rectangles; resize is the only re-measure.

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");

// Modes, per DESIGN.md 6.3. `level` is the resting drive; `running` takes its
// drive from setLevel() instead. `alpha` is the bar wash; terminal states also
// settle the band down to a flat silhouette and then stop the loop.
const MODES = {
  idle:    { level: 0.18, alpha: 0.60, budget: 33, terminal: false, flat: null },
  running: { level: 0.45, alpha: 0.92, budget: 16, terminal: false, flat: null },
  done:    { level: 0.18, alpha: 0.50, budget: 33, terminal: true,  flat: 0.18 },
  refused: { level: 0.14, alpha: 0.45, budget: 33, terminal: true,  flat: 0.14 },
  failed:  { level: 0.12, alpha: 0.45, budget: 33, terminal: true,  flat: 0.12 },
};

const FALLBACK = {
  base: "#0e5a65", mid: "#1c989e", tip: "#5acfd0",
  badBase: "#4a1512", badTip: "#f05b54",
};

// The same ramp in hex. A UA that cannot parse oklch() inside a canvas
// gradient throws on addColorStop; these twins always parse, so the band keeps
// its brand colours rather than taking the module down with it.
const FALLBACK_INK = {
  base: FALLBACK.base, mid: FALLBACK.mid, tip: FALLBACK.tip,
  cap: FALLBACK.tip, bad: FALLBACK.badTip, badBase: FALLBACK.badBase,
};

// How much of the canvas the tallest bar may use, live and settled. The
// gradient is built over exactly this span so a settled band still reaches
// its bright tip instead of showing only the dark base of a full-height ramp.
const SPAN_LIVE = 0.92;
const SPAN_TERM = 0.67;
const REST_MAX = 1.3;   // the peak of the seeded resting profile, see measure()

// One AudioContext for the page, and one MediaElementSource per <audio>:
// createMediaElementSource throws on a second call for the same element, and
// the Review view opens and closes the same item repeatedly.
let audioCtx = null;
const sourceNodes = new WeakMap();
// One analyser per element too. detach() used to null the JS reference and
// leave the node wired to the destination, so every play during a Review
// session left a live node in the graph for the life of the page.
const analyserNodes = new WeakMap();

function readInk(root) {
  const cs = getComputedStyle(root);
  const pick = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
  return {
    base: pick("--teal-700", FALLBACK.base),
    mid: pick("--teal-500", FALLBACK.mid),
    tip: pick("--teal-300", FALLBACK.tip),
    // The peak cap stays inside the one accent family. In --ink it was the
    // brightest mark on an idle page, at double the contrast of the bars it
    // caps and in a hue the token table does not contain.
    cap: pick("--teal-300", FALLBACK.tip),
    bad: pick("--red", FALLBACK.badTip),
    badBase: pick("--red-900", FALLBACK.badBase),
  };
}

const easeExpo = (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p));

// app.js evaluates this at module top level, so anything that throws in here
// would abort app.js and blank the router and all three views. It cannot.
export function mountEq(rootEl) {
  try {
    return mountEqImpl(rootEl);
  } catch {
    return stub();
  }
}

function mountEqImpl(rootEl) {
  const canvas = rootEl && rootEl.querySelector("canvas#eq, canvas");
  if (!canvas || !canvas.getContext) return stub();
  const g = canvas.getContext("2d", { alpha: true });
  if (!g) return stub();

  canvas.setAttribute("aria-hidden", "true");

  const debug = new URLSearchParams(location.search).has("eqdebug");
  let drawMs = 0, drawN = 0, worstMs = 0;

  let mode = "idle";
  let drive = 0;                      // 0..1 from setLevel (the download percent)
  let n = 0, w = 0, h = 0, dpr = 1;
  let bars = new Float32Array(0);
  let caps = new Float32Array(0);
  let held = new Float32Array(0);     // ms remaining on each peak hold
  let phase = new Float32Array(0);
  let speed = new Float32Array(0);
  let tilt = new Float32Array(0);
  let gradLive = null;
  const gradTerm = {};                // one ramp per terminal mode
  let rest = new Float32Array(0);
  let ink = readInk(rootEl);

  let raf = null, last = 0, prev = 0, visible = true;
  let settleStart = 0, settleP = 1;   // 1 = fully settled (terminal silhouette)
  let analyser = null, freqData = null;
  let attachedEl = null, analyserNode = null, currentSrc = null;
  // The audio tap outranks the mode. A Review preview is only ever played
  // AFTER a run has ended, so without this flag the terminal branch below
  // would flatten the analyser's targets and stop the loop, and the band would
  // sit frozen while the Track plays. See DESIGN.md 6.4.
  let tapLive = false;

  // ------------------------------------------------------------- sizing --
  function measure() {
    const r = canvas.getBoundingClientRect();
    dpr = Math.min(2, window.devicePixelRatio || 1);
    w = Math.max(1, Math.round(r.width));
    h = Math.max(1, Math.round(r.height));
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);

    n = Math.max(24, Math.min(96, Math.floor(w / 15)));
    bars = new Float32Array(n);
    caps = new Float32Array(n);
    held = new Float32Array(n);
    rest = new Float32Array(n);
    phase = new Float32Array(n);
    speed = new Float32Array(n);
    tilt = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      // Seeded, not random: two captures of a static frame must match.
      phase[i] = (i * 12.9898) % 6.283;
      speed[i] = 0.5 + ((i * 7919) % 97) / 97 * 1.6;
      tilt[i] = 0.22 + ((i * 104729) % 53) / 53 * 0.5;
      // The settled ridge: a terminal band is low, but it is not a dead flat
      // rectangle. Same seeded profile, so it is reproducible.
      rest[i] = (0.55 + 0.45 * Math.sin((i / n) * Math.PI))
              * (0.55 + 0.75 * Math.abs(Math.sin(i * 0.83 + 0.4)));
    }
    ink = readInk(rootEl);
    if (!buildRamps()) { ink = FALLBACK_INK; buildRamps(); }
    silhouette();
  }

  // Returns false instead of throwing: the horizon is decoration, and app.js
  // evaluates mountEq at module top level, so a colour the UA will not parse
  // must never be able to blank the router and all three views.
  function buildRamps() {
    try {
      const ramp = (span, a, b, c) => {
        const gr = g.createLinearGradient(0, h, 0, h - h * span);
        gr.addColorStop(0, a);
        if (c) gr.addColorStop(0.55, b);
        gr.addColorStop(1, c || b);
        return gr;
      };
      gradLive = ramp(SPAN_LIVE, ink.base, ink.mid, ink.tip);
      // A settled band is short, so its ramp is built over the height that band
      // actually reaches. Over the full canvas the tips would never get past the
      // dark base and a failed run would read as a black smudge.
      for (const [name, m] of Object.entries(MODES)) {
        if (!m.terminal) continue;
        const span = Math.max(0.08, m.flat * 2.0 * REST_MAX * SPAN_TERM);
        const bad = name === "refused" || name === "failed";
        gradTerm[name] = bad ? ramp(span, ink.badBase, ink.bad)
                             : ramp(span, ink.base, ink.tip);
      }
      return true;
    } catch {
      gradLive = null;
      for (const k of Object.keys(gradTerm)) delete gradTerm[k];
      return false;
    }
  }

  // ------------------------------------------------------- motion model --
  function levelNow() {
    if (mode === "running") return 0.45 + 0.4 * drive;
    return MODES[mode].level;
  }

  function synthetic(i, t) {
    const s1 = Math.sin(t * speed[i] * 0.9 + phase[i]);
    const s2 = Math.sin(t * speed[i] * 0.31 + phase[i] * 1.7);
    const s3 = Math.sin(t * 0.17 + i * tilt[i]);
    const shape = 0.55 + 0.45 * Math.sin((i / n) * Math.PI);   // horizon profile
    const v = (0.5 + 0.3 * s1 + 0.25 * s2 + 0.2 * s3) * shape;
    return Math.max(0.05, Math.min(1, v * (0.45 + 0.85 * levelNow())));
  }

  function targets(t, out) {
    if (analyser) {
      try {
        analyser.getByteFrequencyData(freqData);
        const bins = freqData.length - 1;
        for (let i = 0; i < n; i++) {
          const bin = Math.floor(Math.pow(i / n, 1.7) * bins);
          out[i] = Math.min(1, (freqData[bin] / 255) * 1.25);
        }
        return;
      } catch { analyser = null; }
    }
    for (let i = 0; i < n; i++) out[i] = synthetic(i, t);
  }

  const tmp = { arr: new Float32Array(0) };
  function scratch() {
    if (tmp.arr.length !== n) tmp.arr = new Float32Array(n);
    return tmp.arr;
  }

  // ------------------------------------------------------------ drawing --
  function draw() {
    const t0 = debug ? performance.now() : 0;
    const m = MODES[mode];
    const settled = m.terminal && !tapLive;
    const bad = (mode === "refused" || mode === "failed") && !tapLive;
    const gap = 3;
    const bw = (w - gap * (n - 1)) / n;
    // Terminal states ramp the band down over --d-settle; settleP is 0 while
    // a run is live and eases to 1 once it ends.
    const scale = SPAN_LIVE - (SPAN_LIVE - SPAN_TERM) * (settled ? settleP : 0);

    g.clearRect(0, 0, w, h);
    g.globalAlpha = tapLive ? MODES.running.alpha : m.alpha;
    g.fillStyle = (settled ? gradTerm[mode] : gradLive) || ink.base;
    for (let i = 0; i < n; i++) {
      const bh = Math.max(2, bars[i] * h * scale);
      g.fillRect(i * (bw + gap), h - bh, bw, bh);
    }
    g.globalAlpha = (mode === "running" || tapLive) ? 0.85 : 0.45;
    g.fillStyle = bad ? ink.bad : ink.cap;
    for (let i = 0; i < n; i++) {
      const ch = Math.max(3, caps[i] * h * scale);
      g.fillRect(i * (bw + gap), h - ch - 3, bw, 2);
    }
    g.globalAlpha = 1;

    if (debug) {
      const ms = performance.now() - t0;
      drawMs += ms; drawN++;
      if (ms > worstMs) worstMs = ms;
      if (drawN % 120 === 0) {
        console.info(`[eq] n=${n} mean ${(drawMs / drawN).toFixed(3)}ms worst ${worstMs.toFixed(3)}ms over ${drawN} frames`);
      }
    }
  }

  // The seeded silhouette: drawn at mount, at every resize, and as the whole
  // of the design under reduced motion. Evaluated at a fixed t, so two
  // captures a second apart are identical.
  function silhouette() {
    if (!n) return;
    const t = 12.5;
    const m = MODES[mode];
    for (let i = 0; i < n; i++) {
      bars[i] = synthetic(i, t);
      caps[i] = Math.min(1, bars[i] + 0.05);
    }
    settleP = m.terminal ? 1 : settleP;
    draw();
  }

  // --------------------------------------------------------------- loop --
  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (!visible || document.visibilityState === "hidden") { last = now; prev = now; return; }
    const m = MODES[mode];
    if (now - last < (tapLive ? MODES.running.budget : m.budget)) return;
    const dt = Math.min(64, now - (prev || now));
    last = now; prev = now;

    if (m.terminal) {
      settleP = Math.min(1, easeExpo((now - settleStart) / 700));
    }

    const t = now / 1000;
    const tg = scratch();
    targets(t, tg);
    const damp = (mode === "running" || tapLive) ? 0.34 : 0.16;
    // A live tap takes its targets from the analyser, whatever the mode says.
    const flat = tapLive ? null : m.flat;
    for (let i = 0; i < n; i++) {
      const want = flat === null ? tg[i] : flat * 2.0 * rest[i];
      bars[i] += (want - bars[i]) * damp;
      // Peak hold: the cap sits for 620ms before it starts falling. That hold
      // is what makes the band read as a VU meter rather than a trail.
      if (bars[i] >= caps[i]) { caps[i] = bars[i]; held[i] = 620; }
      else if (held[i] > 0) held[i] -= dt;
      else caps[i] = Math.max(bars[i], caps[i] - 0.006);
    }
    if (m.terminal && settleP >= 1 && !tapLive) {
      // The loop is about to stop, so the peak caps are snapped down onto the
      // settled bars: a frozen cap floating over a short bar reads as a bug.
      for (let i = 0; i < n; i++) { caps[i] = bars[i]; held[i] = 0; }
      draw();
      stop();
      return;
    }
    draw();
  }

  // Unwire the analyser and put the element's source back on the speakers.
  // The cached MediaElementSource survives: createMediaElementSource throws on
  // a second call for the same <audio>, and Review reopens the same item.
  function detachTap() {
    try { if (analyserNode) analyserNode.disconnect(); } catch {}
    try {
      if (currentSrc) {
        currentSrc.disconnect();
        if (audioCtx) currentSrc.connect(audioCtx.destination);
      }
    } catch {}
    attachedEl = null; analyserNode = null; currentSrc = null;
  }

  function start() {
    if (raf || REDUCED.matches) return;
    last = 0; prev = 0;
    raf = requestAnimationFrame(frame);
  }
  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = null;
  }

  // ---------------------------------------------------------- observers --
  const io = new IntersectionObserver((entries) => {
    visible = entries[0].isIntersecting;
    // Off-screen stops the loop outright. Flagging it and letting frame()
    // return early still costs a rescheduled callback every frame, which is
    // exactly the budget the horizon is not allowed to spend.
    if (!visible) stop();
    else if (!MODES[mode].terminal || tapLive) start();
  }, { threshold: 0 });
  io.observe(canvas);

  const onVisibility = () => {
    if (document.visibilityState === "hidden") stop();
    else if (!MODES[mode].terminal || tapLive) start();
  };
  document.addEventListener("visibilitychange", onVisibility);

  let resizeRaf = 0;
  const ro = new ResizeObserver(() => {
    if (resizeRaf) return;
    resizeRaf = requestAnimationFrame(() => {
      resizeRaf = 0;
      try { measure(); } catch {}
    });
  });
  ro.observe(canvas);

  const onReduced = () => { if (REDUCED.matches) { stop(); silhouette(); } else start(); };
  REDUCED.addEventListener?.("change", onReduced);

  try {
    measure();
    if (!REDUCED.matches) start();
  } catch {
    // Nothing about the horizon is worth a blank tool. Unwind what was
    // registered and hand back the no-op handle.
    stop();
    io.disconnect(); ro.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    REDUCED.removeEventListener?.("change", onReduced);
    return stub();
  }

  return {
    setMode(next) {
      if (!MODES[next] || next === mode) return;
      mode = next;
      if (MODES[mode].terminal) { settleStart = performance.now(); settleP = 0; }
      else settleP = 0;
      if (REDUCED.matches) { settleP = MODES[mode].terminal ? 1 : 0; silhouette(); return; }
      start();
    },
    setLevel(v) {
      const x = Number(v);
      drive = Number.isFinite(x) ? Math.max(0, Math.min(1, x)) : 0;
    },
    attachAudio(el) {
      // Built inside the play gesture, never at mount. Any throw, a blocked
      // context or a tainted element falls back silently to synthetic motion.
      if (!el) return;
      try {
        const Ctor = window.AudioContext || window.webkitAudioContext;
        if (!Ctor) return;
        audioCtx = audioCtx || new Ctor();
        if (attachedEl !== el) {
          detachTap();
          let src = sourceNodes.get(el);
          if (!src) {
            src = audioCtx.createMediaElementSource(el);
            sourceNodes.set(el, src);
          }
          let node = analyserNodes.get(el);
          if (!node) {
            node = audioCtx.createAnalyser();
            node.fftSize = 128;
            node.smoothingTimeConstant = 0.75;
            analyserNodes.set(el, node);
          }
          try { src.disconnect(); } catch {}
          src.connect(node);
          node.connect(audioCtx.destination);   // the preview still plays aloud
          attachedEl = el; currentSrc = src; analyserNode = node;
        }
        analyser = analyserNode;
        freqData = new Uint8Array(analyserNode.frequencyBinCount);
        if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
        // Set before start(): frame() reads it on the very first tick, and a
        // terminal mode has already stopped the loop by the time we get here.
        tapLive = true;
        if (!REDUCED.matches) start();
      } catch {
        analyser = null;
        tapLive = false;
      }
    },
    detach() {
      // Drop the tap and hand the audio straight back to the speakers. The
      // cached source and analyser stay in the WeakMaps, so reopening the same
      // item attaches again without building a second node.
      detachTap();
      analyser = null;
      freqData = null;
      if (!tapLive) return;
      tapLive = false;
      // A terminal run goes back to the silhouette it was designed to hold,
      // and the loop stops again rather than idling on for the rest of the
      // session. A live mode just carries on synthetically.
      if (REDUCED.matches) { silhouette(); return; }
      if (MODES[mode].terminal) {
        settleP = 1;
        const flat = MODES[mode].flat;
        for (let i = 0; i < n; i++) { bars[i] = flat * 2.0 * rest[i]; caps[i] = bars[i]; held[i] = 0; }
        draw();
        stop();
      }
    },
    stats() {
      return { bars: n, frames: drawN, meanMs: drawN ? drawMs / drawN : 0, worstMs };
    },
    destroy() {
      stop();
      detachTap();
      io.disconnect(); ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      REDUCED.removeEventListener?.("change", onReduced);
    },
  };
}

// If the canvas is missing (a test harness, a stripped page) the shell still
// works: every call is a no-op rather than a thrown error in a view.
function stub() {
  return {
    setMode() {}, setLevel() {}, attachAudio() {}, detach() {},
    stats() { return { bars: 0, frames: 0, meanMs: 0, worstMs: 0 }; },
    destroy() {},
  };
}
