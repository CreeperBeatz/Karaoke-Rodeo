// Karaoke scoring PoC: video + song_map + live mic pitch -> JOYSOUND-style score.
'use strict';

const $ = (id) => document.getElementById(id);
const video = $('video');
const lane = $('lane');
const lctx = lane.getContext('2d');

const state = {
  song: null,        // song_map json
  notes: [],         // decorated notes
  detector: new PitchDetector(),
  running: false,
  trace: [],         // [t, midiFolded, credit]
  combo: 0, maxCombo: 0,
  counts: { PERFECT: 0, GREAT: 0, GOOD: 0, MISS: 0 },
  flipIdx: 0,
  lastFold: 0,
  ended: false,
};

const LS_KEY = 'karaoke_latency';
$('latency').value = localStorage.getItem(LS_KEY) || 140;
$('latencyOut').textContent = $('latency').value + 'ms';
$('latency').oninput = () => {
  $('latencyOut').textContent = $('latency').value + 'ms';
  localStorage.setItem(LS_KEY, $('latency').value);
};

async function loadManifest() {
  const mf = await (await fetch('/songs.json')).json();
  const sel = $('songSel');
  sel.innerHTML = '';
  for (const s of mf.songs) {
    const o = document.createElement('option');
    o.value = JSON.stringify({ map: s.map_url, video: s.video_url });
    o.textContent = `${s.title} ／ ${s.artist}（${s.n_notes}音）`;
    sel.appendChild(o);
  }
  sel.onchange = () => loadSong();
  if (mf.songs.length) await loadSong();
}

async function loadSong() {
  const { map, video: vurl } = JSON.parse($('songSel').value);
  const sm = await (await fetch(map)).json();
  state.song = sm;
  state.notes = sm.notes.map((n) => ({
    ...n,
    dur: Math.max(n.t_end - n.t_start, 0.08),
    hit: 0, sung: 0, done: false, rating: null,
  }));
  state.trace = [];
  state.combo = 0; state.maxCombo = 0;
  state.counts = { PERFECT: 0, GREAT: 0, GOOD: 0, MISS: 0 };
  state.flipIdx = 0;
  state.ended = false;
  const midis = state.notes.map((n) => n.midi);
  state.midiLo = Math.min(...midis) - 2;
  state.midiHi = Math.max(...midis) + 2;
  if (state.midiHi - state.midiLo < 14) {
    const c = (state.midiHi + state.midiLo) / 2;
    state.midiLo = c - 7; state.midiHi = c + 7;
  }
  video.src = vurl;
  updateScoreUI(0);
  ['cPerfect', 'cGreat', 'cGood', 'cMiss'].forEach((id) => ($(id).textContent = '0'));
  $('combo').textContent = '';
}

// ---- mic ----
const LS_MIC = 'karaoke_mic';
async function listMics() {
  // labels/ids are only populated after permission is granted
  const devs = await navigator.mediaDevices.enumerateDevices();
  const mics = devs.filter((d) => d.kind === 'audioinput' && d.deviceId);
  const sel = $('micSel');
  sel.innerHTML = '';
  for (const d of mics) {
    const o = document.createElement('option');
    o.value = d.deviceId;
    o.textContent = d.label || 'マイク';
    sel.appendChild(o);
  }
  const cur = state.detector.stream?.getAudioTracks()[0]?.getSettings().deviceId;
  if (cur) sel.value = cur;
  sel.hidden = mics.length < 2;
}
async function initMic(deviceId) {
  try {
    await state.detector.start(true, deviceId);
    if (deviceId) localStorage.setItem(LS_MIC, deviceId);
    $('startBtn').textContent = '▶ うたう！';
    $('startBtn').disabled = false;
    await listMics();
  } catch (e) {
    console.error(e);
    if (deviceId) return initMic(null); // saved device gone: fall back to default
    $('startBtn').textContent = 'マイクが使えません';
    $('startBtn').disabled = true;
  }
}
initMic(localStorage.getItem(LS_MIC) || null);
$('micSel').onchange = () => initMic($('micSel').value);
navigator.mediaDevices.ondevicechange = () => listMics().catch(() => {});
$('startBtn').onclick = () => {
  state.detector.resume();
  video.currentTime = 0;
  resetScoring();
  video.play();
};
video.onplay = () => { state.running = true; state.detector.resume(); };
video.onpause = () => { state.running = false; };
video.onended = () => finish();

function resetScoring() {
  for (const n of state.notes) { n.hit = 0; n.sung = 0; n.done = false; n.rating = null; }
  state.trace = [];
  state.combo = 0; state.maxCombo = 0;
  state.counts = { PERFECT: 0, GREAT: 0, GOOD: 0, MISS: 0 };
  state.flipIdx = 0;
  state.ended = false;
  ['cPerfect', 'cGreat', 'cGood', 'cMiss'].forEach((id) => ($(id).textContent = '0'));
}

// ---- scoring loop ----
let lastT = null;
function tick() {
  requestAnimationFrame(tick);
  const p = state.detector.analyse();
  $('micLevel').style.width = Math.min(100, state.detector.level * 900) + '%';
  if (!state.song) return;
  const latency = Number($('latency').value) / 1000;
  const t = video.currentTime - latency;
  const dt = lastT === null ? 0 : Math.max(0, t - lastT);
  lastT = t;
  if (state.running && dt > 0 && dt < 0.3) {
    // active note (maps are monophonic; if overlaps remain, latest start wins)
    let active = null;
    for (const n of state.notes) {
      if (n.t_start > t + 0.05) break;
      if (t >= n.t_start && t <= n.t_end) active = n;
    }
    if (p) {
      let target = active ? active.midi : null;
      if (target === null) {
        // fold near previous fold center for a stable trace
        target = state.lastFold || p.midi;
      }
      const folded = p.midi + 12 * Math.round((target - p.midi) / 12);
      state.lastFold = folded;
      let credit = 0;
      if (active) {
        const d = Math.abs(folded - active.midi);
        credit = d <= 0.75 ? 1 : d <= 1.6 ? (1.6 - d) / 0.85 : 0;
        active.hit += dt * credit;
        active.sung += dt;
      }
      state.trace.push([t, folded, credit]);
    } else if (active) {
      active.sung += 0; // silence during note: no credit
    }
    while (state.trace.length && state.trace[0][0] < t - 4.5) state.trace.shift();

    // finalize notes that ended
    for (const n of state.notes) {
      if (!n.done && t > n.t_end) {
        n.done = true;
        if (t - n.t_end > 1.5) { n.acc = 0; n.rating = null; continue; } // skipped (not attempted)
        const acc = Math.min(1, n.hit / n.dur);
        n.acc = acc;
        n.rating = acc >= 0.82 ? 'PERFECT' : acc >= 0.55 ? 'GREAT' : acc >= 0.28 ? 'GOOD' : 'MISS';
        state.counts[n.rating]++;
        if (n.rating === 'MISS') state.combo = 0;
        else { state.combo++; state.maxCombo = Math.max(state.maxCombo, state.combo); }
      }
      if (n.t_start > t) break;
    }
    $('cPerfect').textContent = state.counts.PERFECT;
    $('cGreat').textContent = state.counts.GREAT;
    $('cGood').textContent = state.counts.GOOD;
    $('cMiss').textContent = state.counts.MISS;
    $('combo').textContent = state.combo >= 3 ? `${state.combo} COMBO!` : '';
    updateScoreUI(currentScore());

    // section stamps at page flips
    const flips = state.song.page_flips || [];
    while (state.flipIdx < flips.length && t > flips[state.flipIdx]) {
      const secStart = state.flipIdx > 0 ? flips[state.flipIdx - 1] : 0;
      stampSection(secStart, flips[state.flipIdx]);
      state.flipIdx++;
    }
  }
  drawLane(t);
}
requestAnimationFrame(tick);

function currentScore() {
  let hit = 0, dur = 0;
  for (const n of state.notes) {
    if (!n.done || n.rating === null) continue;
    hit += Math.min(n.hit, n.dur);
    dur += n.dur;
  }
  if (dur < 0.5) return null;
  const A = hit / dur;
  return 100 * Math.pow(A, 0.7);
}

function updateScoreUI(s) {
  if (s === null || s === 0) { $('scoreInt').textContent = '--'; $('scoreDec').textContent = '.---'; return; }
  $('scoreInt').textContent = String(Math.floor(s));
  $('scoreDec').textContent = '.' + String(Math.floor((s % 1) * 1000)).padStart(3, '0');
}

function stampSection(t0, t1) {
  const ns = state.notes.filter((n) => n.done && n.rating !== null && n.t_end > t0 && n.t_end <= t1 + 0.2);
  if (ns.length < 2) return;
  const acc = ns.reduce((a, n) => a + n.acc, 0) / ns.length;
  const el = $('stamp');
  const [txt, col] = acc >= 0.8 ? ['すごい!!', 'var(--gold)']
    : acc >= 0.55 ? ['いいね!', 'var(--cyan)']
    : acc >= 0.3 ? ['おしい…', 'var(--pink)'] : ['がんばれ!', 'var(--miss)'];
  el.textContent = txt;
  el.style.color = col;
  el.classList.remove('show');
  void el.offsetWidth;
  el.classList.add('show');
}

function finish() {
  if (state.ended) return;
  state.ended = true;
  const s = currentScore() || 0;
  $('finalScore').textContent = s.toFixed(3);
  $('finalGrade').textContent = s >= 92 ? '殿堂入り!!' : s >= 85 ? 'プロ級!' : s >= 75 ? 'なかなか!' : s >= 60 ? 'まだまだ!' : '練習あるのみ!';
  $('rPerfect').textContent = state.counts.PERFECT;
  $('rGreat').textContent = state.counts.GREAT;
  $('rGood').textContent = state.counts.GOOD;
  $('rMiss').textContent = state.counts.MISS;
  $('rCombo').textContent = state.maxCombo;
  $('result').showModal();
}

// ---- lane rendering ----
function drawLane(t) {
  const w = lane.width = lane.clientWidth * devicePixelRatio;
  const h = lane.height = 190 * devicePixelRatio;
  const px = devicePixelRatio;
  const T0 = t - 2.2, T1 = t + 5.2;
  const X = (tt) => ((tt - T0) / (T1 - T0)) * w;
  const Y = (m) => h - ((m - state.midiLo) / (state.midiHi - state.midiLo)) * (h - 24 * px) - 12 * px;
  lctx.clearRect(0, 0, w, h);
  if (!state.song) return;

  // octave grid lines (C)
  lctx.font = `${10 * px}px monospace`;
  for (let m = Math.ceil(state.midiLo / 12) * 12; m <= state.midiHi; m += 12) {
    lctx.strokeStyle = 'rgba(139,147,184,0.18)';
    lctx.beginPath(); lctx.moveTo(0, Y(m)); lctx.lineTo(w, Y(m)); lctx.stroke();
    lctx.fillStyle = 'rgba(139,147,184,0.5)';
    lctx.fillText('C' + (m / 12 - 1), 4 * px, Y(m) - 3 * px);
  }
  // now line
  const nx = X(t);
  lctx.strokeStyle = 'rgba(255,255,255,0.35)';
  lctx.lineWidth = 2 * px;
  lctx.beginPath(); lctx.moveTo(nx, 0); lctx.lineTo(nx, h); lctx.stroke();
  lctx.lineWidth = 1 * px;

  // notes
  const bh = Math.max(6 * px, (h / (state.midiHi - state.midiLo)) * 0.9);
  for (const n of state.notes) {
    if (n.t_end < T0 || n.t_start > T1) continue;
    const x0 = X(n.t_start), x1 = X(n.t_end);
    const y = Y(n.midi) - bh / 2;
    let fill;
    if (n.done) {
      fill = n.acc >= 0.55 ? 'rgba(255,198,75,0.95)' : n.acc >= 0.28 ? 'rgba(255,198,75,0.5)' : 'rgba(74,83,117,0.8)';
    } else if (t >= n.t_start && t <= n.t_end) {
      fill = 'rgba(53,214,240,1)';
    } else {
      fill = 'rgba(53,214,240,0.45)';
    }
    lctx.fillStyle = fill;
    roundRect(lctx, x0, y, Math.max(x1 - x0, 3 * px), bh, 3 * px);
    if (n.cls !== 'main') {
      lctx.strokeStyle = n.cls === 'high' ? '#ff4d6d' : '#b06bff';
      lctx.strokeRect(x0 - px, y - px, Math.max(x1 - x0, 3 * px) + 2 * px, bh + 2 * px);
    }
  }
  // sung trace
  if (state.trace.length > 1) {
    lctx.lineWidth = 2.5 * px;
    lctx.lineJoin = 'round';
    let prev = null;
    for (const [tt, m, credit] of state.trace) {
      const x = X(tt), y = Y(m);
      if (prev && tt - prev[0] < 0.12) {
        lctx.strokeStyle = credit > 0.5 ? 'rgba(255,198,75,0.95)' : 'rgba(255,77,143,0.9)';
        lctx.beginPath(); lctx.moveTo(X(prev[0]), Y(prev[1])); lctx.lineTo(x, y); lctx.stroke();
      }
      prev = [tt, m];
    }
    lctx.lineWidth = 1 * px;
  }
}

function roundRect(c, x, y, w, h, r) {
  c.beginPath();
  c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r);
  c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r);
  c.arcTo(x, y, x + w, y, r);
  c.fill();
}

loadManifest();
