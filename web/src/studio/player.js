// Lecteur d'animation des trames : horloge, vitesse, curseur, journal par saut.
// Le dessin est une couche SVG ajoutée au plan ; la logique est dans animation.js.
import { SPEEDS, activeAt, journalRow, timelineBounds } from "./animation.js";
// La forme de la vague : le lobe de l'antenne, calculé sans dépendance au DOM. Une trame
// émise par une sectorielle ne s'étale pas en rond, et le montrer est tout l'intérêt de
// l'animation — sinon autant regarder un disque.
import { contourVague } from "./zone.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const LAYER_ID = "anim-layer";

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

/**
 * @param {object} options
 * @param {(id: string) => {x: number, y: number}|null} options.positionOf écran, par équipement
 * @param {((p: {x_m: number, y_m: number}) => {x: number, y: number})|null} options.project
 *   mètres -> écran. Sans lui, les vagues restent des cercles : on ne peut pas projeter
 *   un lobe avec la seule position de son centre.
 * @param {(id: string) => {x_m: number, y_m: number}|null} options.metresOf position métrique
 * @param {(id: string) => object|null} options.antennaOf antenne déclarée de l'équipement
 * @param {(p: {x_m: number, y_m: number}) => number|null} options.rayonVague portée de la
 *   vague en mètres, à l'instant courant
 */
export function createPlayer({ svg, panel, positionOf, project = null, metresOf = null,
  antennaOf = null, rayonVague = null, onActive = null }) {
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

  /**
   * Le front d'onde d'une émission, à l'instant courant.
   *
   * Un cercle si l'antenne est omnidirectionnelle, inconnue, ou si le plan n'a pas pu
   * être projeté : dans ces cas-là le rond est la forme **neutre**, celle qui n'affirme
   * rien. Un lobe n'est tracé que lorsqu'il est calculable — une vague aplatie faute de
   * projection serait lue comme une antenne défaillante.
   */
  function frontOnde(seg, centreEcran, cls) {
    const r = 14 + 10 * seg.progress;             // pixels : l'échelle de l'anneau d'avant
    const source = metresOf?.(seg.from) ?? null;
    const antenne = antennaOf?.(seg.from) ?? null;
    const porteeM = rayonVague?.(seg.from) ?? null;
    if (project && source && Number.isFinite(porteeM) && porteeM > 0) {
      const contour = contourVague(antenne, source, porteeM, 48);
      const points = [];
      for (const p of contour) {
        const q = project(p);
        // Un sommet qui ne se projette pas : on abandonne le lobe, pas la vague.
        if (!Number.isFinite(q?.x) || !Number.isFinite(q?.y)) {
          return svgEl("circle", { cx: centreEcran.x, cy: centreEcran.y, r, class: `${cls} ring` });
        }
        points.push(`${q.x.toFixed(1)},${q.y.toFixed(1)}`);
      }
      if (points.length >= 4) {
        // Le front pâlit en s'étalant : l'énergie se répartit sur un front plus long, et
        // le voir s'estomper dit « ça s'éloigne » mieux qu'un contour d'épaisseur fixe.
        return svgEl("polygon", { points: points.join(" "), class: `${cls} ring lobe`,
          "stroke-opacity": (1 - 0.55 * (seg.progress ?? 0)).toFixed(3) });
      }
    }
    return svgEl("circle", { cx: centreEcran.x, cy: centreEcran.y, r, class: `${cls} ring` });
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
        // Vers le réseau : le front d'onde autour de l'émetteur. Il prend la forme de
        // l'antenne — une sectorielle éclaire son secteur, un fouet éclaire partout —
        // parce qu'un anneau rond raconterait une antenne que personne n'a déclarée.
        layer.append(frontOnde(seg, from, cls));
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
    if (onActive) onActive(current);
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
      head.textContent = `${row.time} · ${row.source} · ${row.label} · ${row.outcome}`;
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
      // Le journal ne porte que des événements : les descentes réseau n'en sont pas, elles
      // sont reconstituées. Les y ajouter décalerait les index, et l'inspecteur de trames
      // ouvrirait la mauvaise trame. Elles vivent donc dans les segments et dans la note.
      rows = events.map((e) => journalRow(e, groups));
      bounds = timelineBounds(events);
      // La fenêtre doit couvrir les descentes : une classe A répond après son dernier
      // uplink, et une timeline arrêtée à la dernière trame ne la montrerait jamais.
      for (const seg of segs) {
        if (seg.t0 > bounds.endNs) bounds = { ...bounds, endNs: seg.t0 };
      }
      clock = Number(bounds.startNs);
      setPlaying(false);
      renderJournal();
      panel.hidden = false;
      const descentes = segs.filter((s) => s.downlink).length;
      const note = descentes
        ? `${events.length} événements, ${segs.length} sauts `
          + `(dont ${descentes} de descentes réseau).`
        : `${events.length} événements, ${segs.length} sauts.`;
      $("play-note").textContent = note;
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
