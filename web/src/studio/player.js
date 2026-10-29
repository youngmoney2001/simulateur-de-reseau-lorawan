// Lecteur d'animation des trames : horloge, vitesse, curseur, journal par saut.
// Le dessin est une couche SVG ajoutée au plan ; la logique est dans animation.js.
import { SPEEDS, activeAt, journalRow, timelineBounds } from "./animation.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const LAYER_ID = "anim-layer";

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

export function createPlayer({ svg, panel, positionOf }) {
  let segments = [];
  let rows = [];
  let bounds = { startNs: 0n, endNs: 0n };
  let clock = 0; // ns simulées, en nombre (précision suffisante pour une simulation)
  let speed = SPEEDS[1];
  let playing = false;
  let lastFrame = null;
  let rafId = null;

  const $ = (id) => panel.querySelector(`#${id}`);
  const playBtn = $("play-toggle");
  const speedSel = $("play-speed");
  const slider = $("play-clock");
  const label = $("play-time");
  const list = $("journal");

  for (const s of SPEEDS) {
    speedSel.append(new Option(`×${s}`, String(s)));
  }
  speedSel.value = String(speed);

  playBtn.addEventListener("click", () => setPlaying(!playing));
  speedSel.addEventListener("change", () => { speed = Number(speedSel.value); });
  slider.addEventListener("input", () => seek(Number(slider.value) / 1000));

  function span() {
    return Number(bounds.endNs - bounds.startNs);
  }

  function seek(fraction) {
    clock = Number(bounds.startNs) + fraction * span();
    draw();
  }

  function setPlaying(value) {
    playing = value;
    playBtn.textContent = playing ? "Pause" : "Lecture";
    lastFrame = null;
    if (playing && rafId === null) rafId = requestAnimationFrame(tick);
  }

  function tick(now) {
    rafId = null;
    if (!playing) return;
    if (lastFrame !== null) {
      clock += ((now - lastFrame) / 1000) * speed * 1e9;
    }
    lastFrame = now;
    if (clock >= Number(bounds.endNs)) {
      clock = Number(bounds.endNs);
      setPlaying(false);
    }
    draw();
    if (playing) rafId = requestAnimationFrame(tick);
  }

  function ensureLayer() {
    let layer = svg.querySelector(`#${LAYER_ID}`);
    if (!layer) {
      layer = svgEl("g", { id: LAYER_ID });
      svg.append(layer);
    }
    return layer;
  }

  function draw() {
    const layer = ensureLayer();
    while (layer.firstChild) layer.removeChild(layer.firstChild);
    const active = activeAt(segments, BigInt(Math.floor(clock)));
    for (const seg of active) {
      const from = positionOf(seg.from);
      if (!from) continue;
      const to = seg.to ? positionOf(seg.to) : null;
      const cls = `anim-${seg.cls}`;
      if (to) {
        layer.append(svgEl("line", {
          x1: from.x, y1: from.y, x2: to.x, y2: to.y, class: `${cls} trail`,
        }));
        const x = from.x + (to.x - from.x) * seg.progress;
        const y = from.y + (to.y - from.y) * seg.progress;
        layer.append(svgEl("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: 5, class: `${cls} frame` }));
      } else {
        // Vers le réseau : anneau autour de la passerelle source.
        layer.append(svgEl("circle", {
          cx: from.x, cy: from.y, r: 14 + 10 * seg.progress, class: `${cls} ring`,
        }));
      }
    }
    slider.value = String(span() > 0 ? Math.round(((clock - Number(bounds.startNs)) / span()) * 1000) : 0);
    label.textContent = `${(clock / 1e9).toFixed(2)} s / ${(Number(bounds.endNs) / 1e9).toFixed(2)} s`;
    highlightJournal();
  }

  function highlightJournal() {
    let current = -1;
    for (let i = 0; i < rows.length; i += 1) {
      if (Number(rows[i].t_ns) <= clock) current = i;
      else break;
    }
    const items = list.children;
    for (let i = 0; i < items.length; i += 1) {
      items[i].classList.toggle("current", i === current);
    }
    if (current >= 0 && items[current] && playing) items[current].scrollIntoView({ block: "nearest" });
  }

  function renderJournal() {
    while (list.firstChild) list.removeChild(list.firstChild);
    for (const row of rows) {
      const li = document.createElement("li");
      li.className = `journal-row ${row.cls}`;
      li.dataset.seq = String(row.seq);
      const head = document.createElement("button");
      head.type = "button";
      head.className = "journal-head";
      head.textContent = `${row.time} · ${row.source} · ${row.kind} · ${row.outcome}`;
      head.addEventListener("click", () => { setPlaying(false); clock = Number(row.t_ns); draw(); });
      li.append(head);
      if (row.hops.length) {
        const detail = document.createElement("ul");
        for (const h of row.hops) {
          const item = document.createElement("li");
          item.textContent = h;
          detail.append(item);
        }
        li.append(detail);
      }
      list.append(li);
    }
  }

  return {
    // events : TraceEvent[] ; segments : sortie de segmentsFromEvents ; groups : table dispositif -> capteur.
    load({ events, segs, groups }) {
      segments = segs;
      rows = events.map((e) => journalRow(e, groups));
      bounds = timelineBounds(events);
      clock = Number(bounds.startNs);
      setPlaying(false);
      renderJournal();
      panel.hidden = false;
      $("play-note").textContent = `${events.length} événements, ${segs.length} sauts.`;
      draw();
    },
    // Appelé après chaque redessin du plan (qui supprime la couche).
    refresh() {
      if (segments.length) draw();
    },
    clear() {
      setPlaying(false);
      segments = [];
      rows = [];
      while (list.firstChild) list.removeChild(list.firstChild);
      const layer = svg.querySelector(`#${LAYER_ID}`);
      if (layer) layer.remove();
      panel.hidden = true;
    },
  };
}
