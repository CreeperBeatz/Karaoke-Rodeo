// Manual labeling tool for song maps. Backend: /api/label/* (pipeline/labelapi.py).
//
// Model: a song is a list of PAGES; on a page the playhead sweeps linearly, so a
// bar's time is t = T0 + x / R. We edit bar GEOMETRY (x0, x1, pitch row) on a
// still frame of the page — normally the frame just before the page flips, when
// every bar is coloured — and the server recomputes all times on save.
"use strict";

const $ = (id) => document.getElementById(id);
const IMG_H = 270;                     // rows of the 1280x720 frame the stage shows
const S = {
  song: null, notes: [], pages: [], pg: 0, zoom: 1, t: 0,
  sel: null, sug: [], sugT: null, detPh: null, undo: [], redo: [], dirty: false,
  drag: null, mouse: { x: 0, y: 0 }, playing: false, pagescan: null, showSug: true, showLat: false,
};
const cv = $("cv"), ctx = cv.getContext("2d"), still = $("still"), vid = $("vid"), wrap = $("wrap");

// ------------------------------------------------------------------ api
async function api(path, params = {}, body = null) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
  const r = await fetch(`/api/label/${path}?${q}`, body ? { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json" } } : {});
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}
const frameURL = (t, crop = "top") => `/api/label/frame?v=${S.song.id}&t=${t.toFixed(4)}&crop=${crop}`;
function status(msg, cls = "") { const e = $("status"); e.textContent = msg; e.className = cls; }

// ------------------------------------------------------------------ model helpers
const page = () => S.pages[S.pg];
const fps = () => S.song.fps;
const lane = () => S.song.lane;                       // [x0, y0, x1, y1] in frame coords
const lat = () => S.song.lattice;                     // {a, phase}: row centre cy = phase + j*a (lane coords)
const pageNotes = (i = S.pg) => S.notes.filter((n) => n.page === i).sort((a, b) => a.x0 - b.x0);
function tStart(n, p = S.pages[n.page]) { return p.R ? p.T0 + n.x0 / p.R : n.t_start; }
function tEnd(n, p = S.pages[n.page]) { return p.R ? p.T0 + n.x1 / p.R : n.t_end; }
function kOfCy(cy) { return -Math.round((cy - lat().phase) / lat().a); }
function cyOfK(k) { return lat().phase - k * lat().a; }
function snapCy(cy) { return cyOfK(kOfCy(cy)); }
function barH() { return Math.max(6, Math.min(16, lat().a * 0.9)); }
function endTime(p = page()) {  // every bar coloured: sweep just past the last bar (server's t_show, recomputed for edits)
  if (!p.R) { const t = p.t_end - 0.10; return t > p.vis_a ? t : (p.vis_a + p.t_end) / 2; }
  const xr = Math.max(1150, ...pageNotes(S.pages.indexOf(p)).map((n) => n.x1 + 6));
  return Math.max(p.vis_a + 0.05, Math.min(p.T0 + xr / p.R, p.t_end - 0.05));
}
function pageStart(p = page()) { return p.T0 != null ? Math.min(p.vis_a, p.T0) : p.vis_a; }  // page is drawn at T0 (playhead at x=0)
function overlaps(a, b) { return Math.abs(a.cy - b.cy) < 4 && Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0) > 0.4 * Math.min(a.x1 - a.x0, b.x1 - b.x0); }
function cumulativeThrough(i) { return S.notes.filter((n) => n.page <= i).length; }

function snapshot() {
  S.undo.push(JSON.stringify({ notes: S.notes, pages: S.pages }));
  if (S.undo.length > 60) S.undo.shift();
  S.redo.length = 0; S.dirty = true; updateButtons();
}
function restore(str) {
  const o = JSON.parse(str); S.notes = o.notes; S.pages = o.pages; S.sel = null; S.dirty = true;
  renderPages(); draw(); showNote(); showPage();
}
function undo() { if (!S.undo.length) return; S.redo.push(JSON.stringify({ notes: S.notes, pages: S.pages })); restore(S.undo.pop()); updateButtons(); }
function redo() { if (!S.redo.length) return; S.undo.push(JSON.stringify({ notes: S.notes, pages: S.pages })); restore(S.redo.pop()); updateButtons(); }
function updateButtons() {
  $("undoBtn").disabled = !S.undo.length; $("redoBtn").disabled = !S.redo.length;
  $("saveBtn").textContent = S.dirty ? "save *" : "save";
}

// ------------------------------------------------------------------ loading
async function loadSongs() {
  const songs = await api("songs");
  const sel = $("songSel"); sel.innerHTML = "";
  for (const s of songs) {
    const o = document.createElement("option"); o.value = s.id;
    o.textContent = `${s.id} ${s.title} (${s.n_notes}${s.hud_total ? "/" + s.hud_total : ""})`; sel.appendChild(o);
  }
  const m = location.hash.match(/^#(\w+)(?:\/(\d+))?/);   // #v2/6 opens song v2 at page 6
  const want = (m && songs.some((s) => s.id === m[1]) && m[1]) || localStorage.getItem("label_song") || (songs[0] && songs[0].id);
  if (m && m[2]) S.pg = Math.max(0, parseInt(m[2], 10) - 1);
  if (want) { sel.value = want; await loadSong(want, !!(m && m[2])); }
}

async function loadSong(id, keepPage = false) {
  status("loading " + id + " …");
  const st = await api("song", { v: id });
  S.song = st; S.notes = st.notes; S.pages = st.pages; S.sel = null; S.sug = []; S.sugT = null; S.detPh = null;
  S.undo = []; S.redo = []; S.dirty = false; S.pagescan = null;
  S.pg = keepPage ? Math.min(S.pg, S.pages.length - 1) : 0;
  localStorage.setItem("label_song", id);
  vid.pause(); S.playing = false; $("playBtn").textContent = "▶ play";
  vid.src = "/" + encodeURIComponent(st.video);
  $("totHud").textContent = st.hud_total ?? "?";
  layout(); gotoPage(S.pg, true); updateButtons();
  status(`${id}: ${st.notes.length} notes, ${st.pages.length} pages, method ${st.method}`);
}

function layout() {
  const z = S.zoom; const dpr = window.devicePixelRatio || 1;
  wrap.style.width = `${1280 * z}px`; wrap.style.height = `${IMG_H * z}px`;
  still.style.width = `${1280 * z}px`; still.style.height = `${IMG_H * z}px`;
  vid.style.width = `${1280 * z}px`; vid.style.height = `${720 * z}px`;
  cv.style.width = `${1280 * z}px`; cv.style.height = `${IMG_H * z}px`;
  cv.width = Math.round(1280 * z * dpr); cv.height = Math.round(IMG_H * z * dpr);
  $("zoomLabel").textContent = z.toFixed(1) + "×";
  draw();
}

// ------------------------------------------------------------------ pages
function gotoPage(i, force = false) {
  if (i < 0 || i >= S.pages.length) return;
  if (S.playing) togglePlay();
  S.pg = i; S.sel = null; S.sug = []; S.sugT = null; S.detPh = null; $("flip").hidden = true;
  const p = page();
  $("pgLabel").textContent = `page ${i + 1} / ${S.pages.length}`;
  $("scrub").min = pageStart(p).toFixed(3); $("scrub").max = p.t_end.toFixed(3);
  setTime(endTime(p), true);
  renderPages(); showPage(); showNote();
  history.replaceState(null, "", `#${S.song.id}/${i + 1}`);
}

function renderPages() {
  const ul = $("pages"); ul.innerHTML = "";
  S.pages.forEach((p, i) => {
    const li = document.createElement("li"); if (i === S.pg) li.className = "cur";
    const n = pageNotes(i).length;
    let d = "";
    if (S.pagescan) {
      const ns = S.pagescan[i].n_static, diff = ns - n;
      d = `<span class="d ${diff > 0 ? "more" : diff < 0 ? "less" : "eq"}" title="statically detected bars on the end frame: ${ns}">${diff > 0 ? "+" : ""}${diff}</span>`;
    }
    const flag = p.R ? "" : `<span class="flag" title="no sweep model on this page">⚠</span>`;
    li.innerHTML = `<span class="n">${i + 1}</span><span>${p.vis_a.toFixed(1)}s · ${n}${flag}</span>${d}`;
    li.onclick = () => gotoPage(i);
    ul.appendChild(li);
  });
  $("totNotes").textContent = S.notes.length;
  if (S.pagescan) $("totStatic").textContent = `static-detected ${S.pagescan.reduce((a, b) => a + b.n_static, 0)}`;
  const cur = ul.children[S.pg]; if (cur) cur.scrollIntoView({ block: "nearest" });
}

function showPage() {
  const p = page();
  $("pageInfo").innerHTML = [
    ["visible", `${p.vis_a.toFixed(3)} – ${p.t_end.toFixed(3)} s`],
    ["R", p.R ? `${p.R.toFixed(2)} px/s` : "–"], ["T0", p.T0 != null ? `${p.T0.toFixed(4)} s` : "–"],
    ["bars", pageNotes().length], ["cumulative", cumulativeThrough(S.pg)],
  ].map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join("");
  $("cumul").textContent = cumulativeThrough(S.pg);
}

// ------------------------------------------------------------------ time / frame
let frameReq = 0;
function setTime(t, immediate = false) {
  const p = page();
  t = Math.max(pageStart(p), Math.min(p.t_end, t));
  S.t = t; $("scrub").value = t.toFixed(3); $("tLabel").textContent = `${t.toFixed(3)} s`;
  if (!S.playing) {
    const id = ++frameReq;
    const load = () => {
      if (id !== frameReq) return;
      const im = new Image();
      im.onload = () => { if (id === frameReq) { still.src = im.src; drawCounter(im); } };
      im.src = frameURL(t);
    };
    if (immediate) load(); else setTimeout(load, 60);
    scheduleDetect();
  }
  draw();
}

let detTimer = null;
function scheduleDetect() {
  clearTimeout(detTimer);
  detTimer = setTimeout(async () => {
    const t = S.t, v = S.song.id;
    try {
      const [bars, ph] = await Promise.all([api("detect", { v, t }), api("playhead", { v, t })]);
      if (t !== S.t) return;
      S.sug = bars.filter((b) => !pageNotes().some((n) => overlaps(n, b)));
      S.sugT = t; S.detPh = ph; draw();
    } catch (e) { status(e.message, "err"); }
  }, 120);
}

function drawCounter(im) {
  const c = $("counter"), g = c.getContext("2d"); const [x0, y0, x1, y1] = S.song.counter;
  g.fillStyle = "#000"; g.fillRect(0, 0, c.width, c.height);
  g.imageSmoothingEnabled = false;
  const sc = Math.min(c.width / (x1 - x0), c.height / (y1 - y0));
  g.drawImage(im, x0, y0, x1 - x0, y1 - y0, 0, 0, (x1 - x0) * sc, (y1 - y0) * sc);
}

function togglePlay() {
  const p = page();
  if (S.playing) {
    vid.pause(); S.playing = false; $("playBtn").textContent = "▶ play"; vid.hidden = true; still.hidden = false;
    setTime(vid.currentTime, true); return;
  }
  S.playing = true; $("playBtn").textContent = "❚❚ pause"; still.hidden = true; vid.hidden = false;
  vid.currentTime = S.t >= p.t_end - 0.05 ? p.vis_a : S.t; vid.muted = false;
  vid.play().catch((e) => status("video: " + e.message, "err"));
  const loop = () => {
    if (!S.playing) return;
    S.t = vid.currentTime; $("scrub").value = S.t.toFixed(3); $("tLabel").textContent = `${S.t.toFixed(3)} s`;
    draw();
    if (vid.currentTime >= p.t_end || vid.ended) { togglePlay(); return; }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

// ------------------------------------------------------------------ drawing
function draw() {
  if (!S.song) return;
  const z = S.zoom, dpr = window.devicePixelRatio || 1;
  ctx.setTransform(z * dpr, 0, 0, z * dpr, 0, 0);
  ctx.clearRect(0, 0, 1280, IMG_H);
  const [lx0, ly0, lx1, ly1] = lane(); const p = page(); const h = barH();
  ctx.lineWidth = 1 / z;
  if (S.showLat) {
    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    for (let j = -40; j < 80; j++) { const cy = lat().phase + j * lat().a; if (cy < 0 || cy > ly1 - ly0) continue;
      ctx.beginPath(); ctx.moveTo(lx0, ly0 + cy + 0.5); ctx.lineTo(lx1, ly0 + cy + 0.5); ctx.stroke(); }
  }
  // lane frame
  ctx.strokeStyle = "rgba(53,214,240,0.35)"; ctx.strokeRect(lx0 + 0.5, ly0 + 0.5, lx1 - lx0 - 1, ly1 - ly0 - 1);
  // suggestions (static detections without a mapped bar)
  if (S.showSug && S.sugT !== null) {
    ctx.setLineDash([3 / z, 2 / z]); ctx.strokeStyle = "#ff5d5d"; ctx.lineWidth = 1.5 / z;
    for (const b of S.sug) ctx.strokeRect(lx0 + b.x0, ly0 + b.cy - h / 2, b.x1 - b.x0, h);
    ctx.setLineDash([]);
  }
  // notes
  for (const n of pageNotes()) {
    const started = tStart(n, p) <= S.t + 1e-3;
    const col = started ? "#5ef07a" : "#ffc64b";
    ctx.lineWidth = (n === S.sel ? 2.5 : 1.2) / z;
    ctx.strokeStyle = n === S.sel ? "#ffffff" : col;
    ctx.fillStyle = n === S.sel ? "rgba(255,255,255,0.18)" : started ? "rgba(94,240,122,0.10)" : "rgba(255,198,75,0.10)";
    const y = ly0 + n.cy - h / 2;
    ctx.fillRect(lx0 + n.x0, y, n.x1 - n.x0, h); ctx.strokeRect(lx0 + n.x0, y, n.x1 - n.x0, h);
    if (n.cls !== "main") { ctx.fillStyle = n.cls === "high" ? "#ff4d8f" : "#6ab0ff";
      ctx.beginPath(); const tx = lx0 + n.x0 + 3, ty = ly0 + n.cy;
      if (n.cls === "high") { ctx.moveTo(tx, ty + 3); ctx.lineTo(tx + 3, ty - 3); ctx.lineTo(tx + 6, ty + 3); }
      else { ctx.moveTo(tx, ty - 3); ctx.lineTo(tx + 3, ty + 3); ctx.lineTo(tx + 6, ty - 3); }
      ctx.fill(); }
    if (n.src === "manual") { ctx.fillStyle = "#fff"; ctx.fillRect(lx0 + n.x1 - 3, y - 2, 3, 2); }
  }
  // predicted playhead (magenta) and detected playhead runs (cyan ticks)
  if (p.R) {
    const x = lx0 + (S.t - p.T0) * p.R;
    ctx.strokeStyle = "#ff40ff"; ctx.lineWidth = 1 / z; ctx.beginPath(); ctx.moveTo(x + 0.5, ly0 - 8); ctx.lineTo(x + 0.5, ly1 + 8); ctx.stroke();
  }
  if (S.detPh && !S.playing) {
    ctx.strokeStyle = "#35d6f0"; ctx.lineWidth = 2 / z;
    for (const r of S.detPh) { ctx.beginPath(); ctx.moveTo(lx0 + r.x + 0.5, ly1 + 2); ctx.lineTo(lx0 + r.x + 0.5, ly1 + 14); ctx.stroke(); }
  }
}

// ------------------------------------------------------------------ note info / edits
function showNote() {
  const n = S.sel, e = $("noteInfo");
  $("delBtn").disabled = $("clsBtn").disabled = $("flipBtn").disabled = !n;
  if (!n) { e.innerHTML = "<span>–</span><span>click a bar</span>"; return; }
  const base = S.song.midi_base, k = kOfCy(n.cy);
  const midi = base != null ? base + k : null;
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  e.innerHTML = [
    ["x0 – x1", `${n.x0} – ${n.x1} (${n.x1 - n.x0} px)`], ["row cy / k", `${n.cy.toFixed(1)} / ${k}`],
    ["pitch", midi != null ? `${names[midi % 12]}${Math.floor(midi / 12) - 1} (${midi})` : "unanchored"],
    ["t", `${tStart(n).toFixed(3)} – ${tEnd(n).toFixed(3)} s`], ["class", n.cls], ["source", `${n.src}${n.seen ? " · seen " + n.seen : ""}`],
  ].map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join("");
}

function addNote(x0, x1, cy, cls = "main", src = "manual") {
  snapshot();
  const n = { x0: Math.round(x0), x1: Math.round(x1), cy: snapCy(cy), cls, page: S.pg, src, seen: 0 };
  n.k = kOfCy(n.cy); S.notes.push(n); S.sel = n;
  S.sug = S.sug.filter((b) => !overlaps(n, b));
  afterEdit(); return n;
}
function deleteNote(n) { if (!n) return; snapshot(); S.notes = S.notes.filter((m) => m !== n); if (S.sel === n) S.sel = null; afterEdit(); }
function afterEdit() { renderPages(); showPage(); showNote(); draw(); }

function hitNote(x, y) {  // lane coords -> {note, part}
  const h = barH();
  for (const n of pageNotes().reverse()) {
    if (Math.abs(y - n.cy) > h / 2 + 2) continue;
    if (x >= n.x0 - 4 && x <= n.x1 + 4) {
      const part = x - n.x0 <= 4 && n.x1 - n.x0 > 10 ? "x0" : n.x1 - x <= 4 && n.x1 - n.x0 > 10 ? "x1" : "body";
      return { n, part };
    }
  }
  return null;
}
function hitSug(x, y) { return S.showSug ? S.sug.find((b) => Math.abs(y - b.cy) <= barH() / 2 + 2 && x >= b.x0 && x <= b.x1) : null; }

function toLane(ev) {
  const r = cv.getBoundingClientRect(); const [lx0, ly0] = lane();
  return { x: (ev.clientX - r.left) / S.zoom - lx0, y: (ev.clientY - r.top) / S.zoom - ly0 };
}

cv.addEventListener("mousedown", (ev) => {
  if (ev.button !== 0) return;
  const { x, y } = toLane(ev);
  const sg = hitSug(x, y);
  const hit = hitNote(x, y);
  if (hit) {
    S.sel = hit.n; showNote(); draw();
    S.drag = { n: hit.n, part: hit.part, x, y, orig: { x0: hit.n.x0, x1: hit.n.x1, cy: hit.n.cy }, moved: false };
  } else if (sg) {
    addNote(sg.x0, sg.x1, sg.cy, sg.cls); status(`accepted suggestion ${sg.x0}–${sg.x1}`);
  } else { S.sel = null; showNote(); draw(); }
});
window.addEventListener("mousemove", (ev) => {
  if (ev.target === cv) S.mouse = toLane(ev);
  const d = S.drag; if (!d) return;
  const { x, y } = toLane(ev);
  if (!d.moved) { if (Math.abs(x - d.x) < 1 && Math.abs(y - d.y) < 1) return; snapshot(); d.moved = true; }
  const dx = Math.round(x - d.x);
  if (d.part === "x0") d.n.x0 = Math.min(d.orig.x0 + dx, d.n.x1 - 4);
  else if (d.part === "x1") d.n.x1 = Math.max(d.orig.x1 + dx, d.n.x0 + 4);
  else { d.n.x0 = d.orig.x0 + dx; d.n.x1 = d.orig.x1 + dx; d.n.cy = snapCy(d.orig.cy + (y - d.y)); d.n.k = kOfCy(d.n.cy); }
  showNote(); draw();
});
window.addEventListener("mouseup", () => { if (S.drag) { if (S.drag.moved) afterEdit(); S.drag = null; } });
cv.addEventListener("dblclick", (ev) => { addAtCursor(toLane(ev)); });

function addAtCursor({ x, y }) {
  if (hitNote(x, y)) return;
  const sg = hitSug(x, y);
  if (sg) { addNote(sg.x0, sg.x1, sg.cy, sg.cls); return; }
  // no suggestion here: ask the server for ANY colored bar under the cursor (no lattice filter, strict off)
  api("detect", { v: S.song.id, t: S.t, nolattice: 1 }).then((bars) => {
    const b = bars.find((b) => Math.abs(b.cy - y) <= 8 && x >= b.x0 - 2 && x <= b.x1 + 2);
    if (b) addNote(b.x0, b.x1, b.cy, b.cls); else addNote(x - 20, x + 20, y);
    status(b ? "added detected bar" : "added default bar (drag edges to fit)");
  }).catch((e) => { addNote(x - 20, x + 20, y); status(e.message, "err"); });
}

function splitAtCursor() {
  const n = S.sel; if (!n) return;
  const x = Math.round(S.mouse.x);
  if (x - n.x0 < 4 || n.x1 - x < 4) { status("cursor must be inside the selected bar", "err"); return; }
  snapshot();
  const m = { ...n, x0: x + 2, src: "manual", seen: 0 }; n.x1 = x - 1; S.notes.push(m); S.sel = m; afterEdit();
}
function mergeRight() {
  const n = S.sel; if (!n) return;
  const right = pageNotes().filter((m) => m !== n && Math.abs(m.cy - n.cy) < 2 && m.x0 >= n.x1 - 2).sort((a, b) => a.x0 - b.x0)[0];
  if (!right) { status("no bar to the right on this row", "err"); return; }
  snapshot(); n.x1 = right.x1; S.notes = S.notes.filter((m) => m !== right); afterEdit();
}
function acceptAll() {
  if (!S.sug.length) { status("no suggestions on this page", "err"); return; }
  snapshot();
  for (const b of S.sug) { const n = { x0: b.x0, x1: b.x1, cy: snapCy(b.cy), cls: b.cls, page: S.pg, src: "manual", seen: 0 }; n.k = kOfCy(n.cy); S.notes.push(n); }
  status(`accepted ${S.sug.length} suggestions`); S.sug = []; afterEdit();
}
function nudgeRow(dk) { const n = S.sel; if (!n) return; snapshot(); n.k = kOfCy(n.cy) + dk; n.cy = cyOfK(n.k); afterEdit(); }
function nudgeX(d, edge) { const n = S.sel; if (!n) return; snapshot();
  if (edge) n.x1 = Math.max(n.x0 + 4, n.x1 + d); else n.x0 = Math.min(n.x1 - 4, n.x0 + d); afterEdit(); }
function cycleClass() { const n = S.sel; if (!n) return; snapshot(); n.cls = { main: "high", high: "low", low: "main" }[n.cls] || "main"; afterEdit(); }

async function flipStrip() {
  const n = S.sel; if (!n) return;
  const im = $("flip"); im.hidden = false;
  im.src = `/api/label/flipstrip?v=${S.song.id}&x0=${n.x0}&x1=${n.x1}&cy=${n.cy}&cls=${n.cls}&t=${tStart(n).toFixed(4)}&_=${Date.now()}`;
}

// ------------------------------------------------------------------ page timing
function shiftT0(frames) {
  const p = page(); if (!p.R) { status("page has no sweep model", "err"); return; }
  snapshot(); const d = frames / fps();
  p.T0 += d; p.vis_a += d; if (S.pg > 0) S.pages[S.pg - 1].t_end = p.vis_a;
  $("scrub").min = pageStart(p).toFixed(3); afterEdit(); status(`T0 shifted ${frames > 0 ? "+" : ""}${frames} frame`);
}
function proposal(html, apply) {
  const e = $("proposal"); e.innerHTML = html;
  if (apply) { const b = document.createElement("button"); b.textContent = "apply"; b.className = "warn"; b.style.marginLeft = "8px";
    b.onclick = () => { apply(); e.innerHTML = ""; }; e.appendChild(b); }
}
async function refitPlayhead() {
  const p = page(); status("refitting from playhead …");
  try {
    const r = await api("refit_playhead", { v: S.song.id, t_a: p.vis_a, t_b: p.t_end, R: p.R, T0: p.T0 });
    if (!r.ok) { proposal(`playhead: ${r.msg} (${r.n} detections)`); status(r.msg, "err"); return; }
    status(`playhead fit: R ${r.R} T0 ${r.T0} from ${r.n} frames, median residual ${r.med_res} px`);
    proposal(`playhead → R ${r.R} (was ${p.R ? p.R.toFixed(2) : "–"}), T0 ${r.T0} (was ${p.T0 != null ? p.T0.toFixed(4) : "–"}), ${r.n} pts, res ${r.med_res} px`,
      () => applyFit(r.R, r.T0));
  } catch (e) { status(e.message, "err"); }
}
async function refitFlips() {
  const p = page(); status("refitting from colour flips (binary searches, ~10 s) …");
  try {
    const r = await api("refit_flips", {}, { v: S.song.id, page: p, notes: pageNotes() });
    if (!r.ok) { proposal(`flips: ${r.msg}`); status(r.msg, "err"); return; }
    status(`flip fit: R ${r.R} T0 ${r.T0}, ${r.n_in}/${r.n_pts} bars on the line`);
    proposal(`flips → R ${r.R} (was ${p.R ? p.R.toFixed(2) : "–"}), T0 ${r.T0} (was ${p.T0 != null ? p.T0.toFixed(4) : "–"}), ${r.n_in}/${r.n_pts} inliers`,
      () => applyFit(r.R, r.T0));
  } catch (e) { status(e.message, "err"); }
}
function applyFit(R, T0) {
  const p = page(); snapshot();
  const xlo = p.R ? (p.vis_a - p.T0) * p.R : 40;      // keep the page's visible-start column
  p.R = R; p.T0 = T0; p.vis_a = T0 + xlo / R;
  if (S.pg > 0) S.pages[S.pg - 1].t_end = p.vis_a;
  $("scrub").min = pageStart(p).toFixed(3); afterEdit();
}

// ------------------------------------------------------------------ scan / save
async function scanPages() {
  status("scanning end frames of all pages …"); $("scanBtn").disabled = true;
  try { S.pagescan = await api("pagescan", { v: S.song.id }, { pages: S.pages, notes: S.notes }); renderPages(); status("page scan done: red +n = detected bars without a mapped note"); }
  catch (e) { status(e.message, "err"); }
  $("scanBtn").disabled = false;
}
async function save() {
  if (!S.song) return;
  status("saving …"); $("saveBtn").disabled = true;
  try {
    const r = await api("save", {}, { v: S.song.id, pages: S.pages, notes: S.notes });
    status(`saved ${r.n_notes} notes / ${r.n_pages} pages → ${r.path}`, "ok");
    const pg = S.pg; await loadSong(S.song.id, true); S.pg = pg; gotoPage(pg, true);
  } catch (e) { status("save failed: " + e.message, "err"); }
  $("saveBtn").disabled = false;
}

// ------------------------------------------------------------------ wiring
$("songSel").onchange = (e) => { if (S.dirty && !confirm("Discard unsaved edits?")) { e.target.value = S.song.id; return; } S.pg = 0; loadSong(e.target.value); };
$("prevPg").onclick = () => gotoPage(S.pg - 1); $("nextPg").onclick = () => gotoPage(S.pg + 1);
$("scanBtn").onclick = scanPages; $("saveBtn").onclick = save; $("undoBtn").onclick = undo; $("redoBtn").onclick = redo;
$("zoom").oninput = (e) => { S.zoom = parseFloat(e.target.value); layout(); };
$("showSug").onchange = (e) => { S.showSug = e.target.checked; draw(); };
$("showLat").onchange = (e) => { S.showLat = e.target.checked; draw(); };
$("scrub").oninput = (e) => { if (S.playing) togglePlay(); setTime(parseFloat(e.target.value)); };
$("endBtn").onclick = () => { if (S.playing) togglePlay(); setTime(endTime(), true); };
$("playBtn").onclick = togglePlay;
$("stepB").onclick = () => { if (S.playing) togglePlay(); setTime(S.t - 1 / fps(), true); };
$("stepF").onclick = () => { if (S.playing) togglePlay(); setTime(S.t + 1 / fps(), true); };
$("t0m").onclick = () => shiftT0(-1); $("t0p").onclick = () => shiftT0(1);
$("refitPh").onclick = refitPlayhead; $("refitFl").onclick = refitFlips;
$("flipBtn").onclick = flipStrip; $("delBtn").onclick = () => deleteNote(S.sel); $("clsBtn").onclick = cycleClass;

window.addEventListener("keydown", (ev) => {
  if (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT") return;
  const k = ev.key;
  if (ev.ctrlKey && k.toLowerCase() === "z") { ev.preventDefault(); undo(); return; }
  if (ev.ctrlKey && k.toLowerCase() === "y") { ev.preventDefault(); redo(); return; }
  if (ev.ctrlKey && k.toLowerCase() === "s") { ev.preventDefault(); save(); return; }
  switch (k) {
    case "PageUp": ev.preventDefault(); gotoPage(S.pg - 1); break;
    case "PageDown": ev.preventDefault(); gotoPage(S.pg + 1); break;
    case "End": ev.preventDefault(); if (S.playing) togglePlay(); setTime(endTime(), true); break;
    case " ": ev.preventDefault(); togglePlay(); break;
    case ",": if (S.playing) togglePlay(); setTime(S.t - 1 / fps(), true); break;
    case ".": if (S.playing) togglePlay(); setTime(S.t + 1 / fps(), true); break;
    case "Escape": S.sel = null; showNote(); draw(); break;
    case "Delete": case "Backspace": ev.preventDefault(); deleteNote(S.sel); break;
    case "ArrowUp": ev.preventDefault(); nudgeRow(1); break;
    case "ArrowDown": ev.preventDefault(); nudgeRow(-1); break;
    case "ArrowLeft": ev.preventDefault(); nudgeX(-1, ev.shiftKey); break;
    case "ArrowRight": ev.preventDefault(); nudgeX(1, ev.shiftKey); break;
    case "n": case "N": addAtCursor(S.mouse); break;
    case "a": { const sg = hitSug(S.mouse.x, S.mouse.y); if (sg) addNote(sg.x0, sg.x1, sg.cy, sg.cls); else status("no suggestion under cursor", "err"); break; }
    case "A": acceptAll(); break;
    case "s": case "S": splitAtCursor(); break;
    case "m": case "M": mergeRight(); break;
    case "c": case "C": cycleClass(); break;
    case "f": case "F": flipStrip(); break;
    case "l": case "L": S.showLat = !S.showLat; $("showLat").checked = S.showLat; draw(); break;
    default: return;
  }
});
window.addEventListener("beforeunload", (ev) => { if (S.dirty) { ev.preventDefault(); ev.returnValue = ""; } });
window.addEventListener("resize", draw);

loadSongs().catch((e) => status(e.message, "err"));
