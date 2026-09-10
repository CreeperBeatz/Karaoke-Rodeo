// Play page: video + song_map + live mic pitch -> JOYSOUND-style score, saved to the account (or a party member).
import { api, renderNav, requireLogin, el, $, avatarEl, fmtScore, grade, toast, qs } from '/static/common.js';
import { onParty, currentSinger, refreshParty } from '/static/party.js';

const video = $('video');
const lane = $('lane');
const lctx = lane.getContext('2d');
const songId = qs('song');
if (!songId) location.replace('/');

const state = {
  song: null, notes: [], detector: new PitchDetector(), running: false, trace: [],
  combo: 0, maxCombo: 0, counts: { PERFECT: 0, GREAT: 0, GOOD: 0, MISS: 0 }, flipIdx: 0, lastFold: 0, ended: false,
  party: null, submitting: false,
};

await renderNav('/');
const me = await requireLogin();

// ---- latency: account value, mirrored to localStorage for instant reuse ----
$('latency').value = me.latency_ms ?? localStorage.getItem('karaoke_latency') ?? 140;
$('latencyOut').textContent = $('latency').value + 'ms';
let latSave;
$('latency').oninput = () => {
  $('latencyOut').textContent = $('latency').value + 'ms';
  localStorage.setItem('karaoke_latency', $('latency').value);
  clearTimeout(latSave);
  latSave = setTimeout(() => api('/api/me', { method: 'PATCH', body: { latency_ms: Number($('latency').value) } }).catch(() => {}), 800);
};

// ---- song ----
async function loadSong() {
  const [info, sm] = await Promise.all([api(`/api/songs/${encodeURIComponent(songId)}`), api(`/api/songs/${encodeURIComponent(songId)}/map`)]);
  state.info = info;
  state.song = sm;
  $('title').textContent = info.title_jp || info.title_en || songId;
  $('artist').textContent = info.artist_jp || info.artist_en || '';
  document.title = `${$('title').textContent} — カラオケ.ロデオ`;
  state.notes = sm.notes.map((n) => ({ ...n, dur: Math.max(n.t_end - n.t_start, 0.08), hit: 0, sung: 0, done: false, rating: null, cents: 0, centsW: 0 }));
  const midis = state.notes.map((n) => n.midi);
  state.midiLo = Math.min(...midis) - 2;
  state.midiHi = Math.max(...midis) + 2;
  if (state.midiHi - state.midiLo < 14) { const c = (state.midiHi + state.midiLo) / 2; state.midiLo = c - 7; state.midiHi = c + 7; }
  video.src = `/media/${encodeURIComponent(songId)}`;
  resetScoring();
  showBest();
}
function showBest() {
  const b = state.info?.my_best;
  $('myBest').textContent = b != null ? `自己ベスト ${fmtScore(b)}` : 'はじめての曲';
}

// ---- mic ----
const LS_MIC = 'karaoke_mic';
async function listMics() {
  const devs = await navigator.mediaDevices.enumerateDevices();
  const mics = devs.filter((d) => d.kind === 'audioinput' && d.deviceId);
  const sel = $('micSel');
  sel.innerHTML = '';
  for (const d of mics) sel.append(el('option', { value: d.deviceId }, d.label || 'マイク'));
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
    if (deviceId) return initMic(null);
    $('startBtn').textContent = 'マイクが使えません';
    $('startBtn').disabled = true;
  }
}
initMic(localStorage.getItem(LS_MIC) || null);
$('micSel').onchange = () => initMic($('micSel').value);
navigator.mediaDevices.ondevicechange = () => listMics().catch(() => {});

$('startBtn').onclick = () => { state.detector.resume(); video.currentTime = 0; resetScoring(); video.play(); };
video.onplay = () => { state.running = true; state.detector.resume(); $('quitBtn').hidden = false; };
video.onpause = () => { state.running = false; };
video.onended = () => finish(true);
$('quitBtn').onclick = () => { video.pause(); finish(false); };
$('again').onclick = () => { $('result').close(); $('startBtn').click(); };

function resetScoring() {
  for (const n of state.notes) { n.hit = 0; n.sung = 0; n.done = false; n.rating = null; n.acc = 0; n.cents = 0; n.centsW = 0; }
  state.trace = []; state.combo = 0; state.maxCombo = 0;
  state.counts = { PERFECT: 0, GREAT: 0, GOOD: 0, MISS: 0 };
  state.flipIdx = 0; state.ended = false; state.lastFold = 0;
  ['cPerfect', 'cGreat', 'cGood', 'cMiss'].forEach((id) => ($(id).textContent = '0'));
  $('combo').textContent = '';
  updateScoreUI(0);
}

// ---- scoring loop (unchanged model from the PoC: octave-tolerant, time-weighted credit) ----
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
    let active = null;
    for (const n of state.notes) {
      if (n.t_start > t + 0.05) break;
      if (t >= n.t_start && t <= n.t_end) active = n;
    }
    if (p) {
      let target = active ? active.midi : null;
      if (target === null) target = state.lastFold || p.midi;
      const folded = p.midi + 12 * Math.round((target - p.midi) / 12);
      state.lastFold = folded;
      let credit = 0;
      if (active) {
        const d = Math.abs(folded - active.midi);
        credit = d <= 0.75 ? 1 : d <= 1.6 ? (1.6 - d) / 0.85 : 0;
        active.hit += dt * credit;
        active.sung += dt;
        if (d <= 1.6) { active.cents += (folded - active.midi) * 100 * dt; active.centsW += dt; }
      }
      state.trace.push([t, folded, credit]);
    }
    while (state.trace.length && state.trace[0][0] < t - 4.5) state.trace.shift();
    for (const n of state.notes) {
      if (!n.done && t > n.t_end) {
        n.done = true;
        if (t - n.t_end > 1.5) { n.acc = 0; n.rating = null; continue; } // skipped (seeked past): not attempted
        const acc = Math.min(1, n.hit / n.dur);
        n.acc = acc;
        n.rating = acc >= 0.82 ? 'PERFECT' : acc >= 0.55 ? 'GREAT' : acc >= 0.28 ? 'GOOD' : 'MISS';
        state.counts[n.rating]++;
        if (n.rating === 'MISS') state.combo = 0;
        else { state.combo++; state.maxCombo = Math.max(state.maxCombo, state.combo); }
      }
      if (n.t_start > t) break;
    }
    $('cPerfect').textContent = state.counts.PERFECT; $('cGreat').textContent = state.counts.GREAT;
    $('cGood').textContent = state.counts.GOOD; $('cMiss').textContent = state.counts.MISS;
    $('combo').textContent = state.combo >= 3 ? `${state.combo} COMBO!` : '';
    updateScoreUI(currentScore());
    const flips = state.song.page_flips || [];
    while (state.flipIdx < flips.length && t > flips[state.flipIdx]) {
      stampSection(state.flipIdx > 0 ? flips[state.flipIdx - 1] : 0, flips[state.flipIdx]);
      state.flipIdx++;
    }
  }
  drawLane(t);
}
requestAnimationFrame(tick);

function currentScore() {
  let hit = 0, dur = 0;
  for (const n of state.notes) { if (!n.done || n.rating === null) continue; hit += Math.min(n.hit, n.dur); dur += n.dur; }
  if (dur < 0.5) return null;
  return 100 * Math.pow(hit / dur, 0.7);
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
  const e = $('stamp');
  const [txt, col] = acc >= 0.8 ? ['すごい!!', 'var(--gold)'] : acc >= 0.55 ? ['いいね!', 'var(--cyan)'] : acc >= 0.3 ? ['おしい…', 'var(--pink)'] : ['がんばれ!', 'var(--miss)'];
  e.textContent = txt; e.style.color = col; e.classList.remove('show'); void e.offsetWidth; e.classList.add('show');
}

// ---- finish + submit ----
const RATING_IDX = { MISS: 0, GOOD: 1, GREAT: 2, PERFECT: 3 };
async function finish(completed) {
  if (state.ended) return;
  state.ended = true;
  state.running = false;
  $('quitBtn').hidden = true;
  const s = currentScore() || 0;
  $('finalScore').textContent = s.toFixed(3);
  $('finalGrade').textContent = completed ? grade(s) : '途中終了（ランキング対象外）';
  $('rPerfect').textContent = state.counts.PERFECT; $('rGreat').textContent = state.counts.GREAT;
  $('rGood').textContent = state.counts.GOOD; $('rMiss').textContent = state.counts.MISS; $('rCombo').textContent = state.maxCombo;
  $('rPb').textContent = ''; $('rRank').textContent = '保存中…';
  const singer = currentSinger();
  $('rWho').textContent = singer ? `RESULT — ${singer.name}` : 'RESULT';
  $('result').showModal();
  const attempted = state.notes.some((n) => n.rating !== null);
  if (!attempted) { $('rRank').textContent = '歌っていないので保存しません'; return; }
  const results = { notes: state.notes.map((n) => n.rating === null ? [null, 0, null]
    : [RATING_IDX[n.rating], Math.round(n.acc * 1000) / 1000, n.centsW > 0.05 ? Math.round(n.cents / n.centsW) : null]) };
  try {
    const r = await api('/api/plays', { method: 'POST', body: {
      song_id: songId, score: s, counts: state.counts, max_combo: state.maxCombo, completed, latency_ms: Number($('latency').value), results,
      party_code: state.party?.code || null, member_id: singer?.id || null } });
    if (completed) {
      if (r.is_pb) $('rPb').textContent = r.best_before == null ? '★ はじめての記録！' : `★ 自己ベスト更新！ (+${(s - r.best_before).toFixed(3)})`;
      else if (r.best_before != null) $('rPb').textContent = `自己ベスト ${fmtScore(r.best_before)}`;
      $('rRank').textContent = r.rank ? `この曲で ${r.rank}位 / ${r.n_players}人` : (singer && singer.is_guest ? 'ゲストの記録はパーティー内のみ' : '');
      if (!singer || !singer.is_guest) { state.info.my_best = Math.max(state.info.my_best ?? 0, s); if (!singer) showBest(); }
    } else $('rRank').textContent = '記録は保存しました（未完走）';
    if (state.party) refreshParty();
  } catch (e) {
    $('rRank').textContent = '保存できませんでした: ' + e.message;
  }
}

// ---- party mode (app-level: the strip under the header owns it; here we only follow who is singing) ----
const SOLO_HIT = 'rgba(255,198,75,0.95)';   // gold trace when singing alone
onParty((p) => {
  state.party = p;
  const cur = currentSinger();
  const box = $('singer');
  box.hidden = !cur;
  if (cur) {
    box.style.setProperty('--seat', cur.color);
    box.replaceChildren(el('i', { class: 'dot' }), avatarEl(cur), el('span', {}, 'うたう人: ', el('b', {}, cur.name)));
  }
});

// ---- lane rendering ----
function drawLane(t) {
  const w = lane.width = lane.clientWidth * devicePixelRatio;
  const h = lane.height = Math.max(80, lane.clientHeight) * devicePixelRatio;
  const px = devicePixelRatio;
  const T0 = t - 2.2, T1 = t + 5.2;
  const X = (tt) => ((tt - T0) / (T1 - T0)) * w;
  const Y = (m) => h - ((m - state.midiLo) / (state.midiHi - state.midiLo)) * (h - 24 * px) - 12 * px;
  lctx.clearRect(0, 0, w, h);
  if (!state.song) return;
  lctx.font = `${10 * px}px monospace`;
  for (let m = Math.ceil(state.midiLo / 12) * 12; m <= state.midiHi; m += 12) {
    lctx.strokeStyle = 'rgba(139,147,184,0.18)';
    lctx.beginPath(); lctx.moveTo(0, Y(m)); lctx.lineTo(w, Y(m)); lctx.stroke();
    lctx.fillStyle = 'rgba(139,147,184,0.5)';
    lctx.fillText('C' + (m / 12 - 1), 4 * px, Y(m) - 3 * px);
  }
  const nx = X(t);
  lctx.strokeStyle = 'rgba(255,255,255,0.35)'; lctx.lineWidth = 2 * px;
  lctx.beginPath(); lctx.moveTo(nx, 0); lctx.lineTo(nx, h); lctx.stroke();
  lctx.lineWidth = 1 * px;
  const bh = Math.max(6 * px, (h / (state.midiHi - state.midiLo)) * 0.9);
  for (const n of state.notes) {
    if (n.t_end < T0 || n.t_start > T1) continue;
    const x0 = X(n.t_start), x1 = X(n.t_end);
    const y = Y(n.midi) - bh / 2;
    let fill;
    if (n.done) fill = n.acc >= 0.55 ? 'rgba(255,198,75,0.95)' : n.acc >= 0.28 ? 'rgba(255,198,75,0.5)' : 'rgba(74,83,117,0.8)';
    else if (t >= n.t_start && t <= n.t_end) fill = 'rgba(53,214,240,1)';
    else fill = 'rgba(53,214,240,0.45)';
    lctx.fillStyle = fill;
    roundRect(lctx, x0, y, Math.max(x1 - x0, 3 * px), bh, 3 * px);
    if (n.cls !== 'main') {
      lctx.strokeStyle = n.cls === 'high' ? '#ff4d6d' : '#b06bff';
      lctx.strokeRect(x0 - px, y - px, Math.max(x1 - x0, 3 * px) + 2 * px, bh + 2 * px);
    }
  }
  if (state.trace.length > 1) {
    lctx.lineWidth = 2.5 * px; lctx.lineJoin = 'round';
    let prev = null;
    for (const [tt, m, credit] of state.trace) {
      const x = X(tt), y = Y(m);
      if (prev && tt - prev[0] < 0.12) {
        lctx.strokeStyle = credit > 0.5 ? hitColour() : 'rgba(255,77,143,0.9)';
        lctx.beginPath(); lctx.moveTo(X(prev[0]), Y(prev[1])); lctx.lineTo(x, y); lctx.stroke();
      }
      prev = [tt, m];
    }
    lctx.lineWidth = 1 * px;
  }
}
/** On-pitch trace colour: the current party seat's colour, or gold when singing alone. */
function hitColour() {
  const cur = currentSinger();
  return cur ? cur.color : SOLO_HIT;
}
function roundRect(c, x, y, w, h, r) {
  c.beginPath(); c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r);
  c.fill();
}

loadSong().catch((e) => { toast(e.message, 'err'); $('title').textContent = '読み込めません'; });
