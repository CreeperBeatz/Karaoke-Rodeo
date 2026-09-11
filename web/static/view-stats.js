// きろく - tiles, practice calendar, per-song trend and weak sections, by-note accuracy, recent plays.
import { api, el, $, fmtScore, fmtDate, fmtAgo } from '/static/common.js';

const NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
const fmtT = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
// sequential single-hue ramp (cyan): dark = weak, bright = strong
function heatColor(a) { const stops = ['#0f2a33', '#145c6a', '#1a7a8c', '#1f93aa', '#2ab6cf', '#35d6f0']; return stops[Math.min(5, Math.floor(a * 6))]; }

export default {
  title: 'きろく',
  auth: true,
  load: () => api(`/api/me/stats?tz=${new Date().getTimezoneOffset()}`),

  render(main, D) {
    main.innerHTML = `
  <h1>きろく <span class="sub">your stats</span></h1>
  <div class="tiles" id="tiles"></div>

  <section class="sec panel">
    <h3>練習カレンダー <span class="sub">practice calendar</span></h3>
    <div class="calwrap"><div class="cal" id="cal"></div></div>
    <div class="legend">少ない <i style="background:var(--panel-3)"></i><i class="l1" style="background:#145c6a"></i><i style="background:#1f93aa"></i><i style="background:#35d6f0"></i> 多い　<span id="calNote"></span></div>
  </section>

  <section class="sec">
    <div class="songtabs" id="songtabs"></div>
    <div class="two">
      <div class="panel"><h3>点数の推移 <span class="sub">score trend</span></h3><div class="chart" id="trend"></div></div>
      <div class="panel weaklist"><h3>にがてな区間 <span class="sub">weak sections</span></h3>
        <div class="dim" style="font-size:13.5px">直近5回の区間ごとの命中率。暗い＝にがて。</div>
        <div class="heat" id="heat" style="margin-top:8px"></div>
        <ul id="weak"></ul></div>
    </div>
  </section>

  <section class="sec panel">
    <h3>音ごとの正確さ <span class="sub">pitch accuracy by note</span></h3>
    <div class="dim" style="font-size:13.5px">全曲・全回。棒＝その音を当てた割合。↑は高め（シャープ）、↓は低め（フラット）に外しがち。</div>
    <div class="chart" id="notes"></div>
  </section>

  <section class="sec panel tablewrap">
    <h3>最近の記録 <span class="sub">recent plays</span></h3>
    <table id="recent"></table>
  </section>`;

    const S = D.summary;
    // The content box of a .chart panel. During a view transition the element can measure 0, so fall back to
    // the page width less the padding the panel and the page put around it.
    const chartWidth = (node) => {
      const w = node.clientWidth - 12;                 // .chart has 6px of side padding
      return w > 80 ? w : Math.max(260, Math.min(1100, innerWidth) - 96);
    };
    const tip = $('tip');
    const showTip = (e, html) => {
      tip.innerHTML = html;
      tip.hidden = false;
      // clamp into the viewport on both axes - on a phone the touch point is often near an edge, and a tip
      // placed above the finger would otherwise sit off the top of the screen
      const w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = Math.max(8, Math.min(e.clientX + 14, innerWidth - w - 8)) + 'px';
      tip.style.top = Math.max(8, Math.min(e.clientY - 34, innerHeight - h - 8)) + 'px';
    };
    const hideTip = () => (tip.hidden = true);
    /** Show `html(e)` while the pointer is over `node` - hover for a mouse, touch-and-hold for a finger. */
    const bindTip = (node, html, onShow, onHide) => {
      // No preventDefault: the by-note chart scrolls sideways under the finger, and a drag that turns into a
      // scroll fires pointercancel, which takes the tip down on its own.
      const show = (e) => { onShow?.(e); showTip(e, html(e)); };
      const hide = () => { onHide?.(); hideTip(); };
      node.addEventListener('pointerenter', show);
      node.addEventListener('pointermove', show);
      node.addEventListener('pointerdown', show);
      node.addEventListener('pointerup', hide);
      node.addEventListener('pointerleave', hide);
      node.addEventListener('pointercancel', hide);
    };

    // --- tiles ---
    const tile = (label, value, note, cls = '') => el('div', { class: 'tile' }, el('div', { class: 'label' }, label), el('div', { class: `value ${cls}` }, value), note ? el('div', { class: 'note' }, note) : null);
    $('tiles').replaceChildren(
      tile('うたった回数', S.n_plays, `${S.n_songs}曲`),
      tile('平均ベスト', S.avg_best != null ? fmtScore(S.avg_best) : '--', '曲ごとの自己ベストの平均'),
      tile('最高得点', S.best ? fmtScore(S.best.score) : '--', S.best ? S.best.title_jp : ''),
      tile('連続日数', `${S.streak}日`, `最長 ${S.longest_streak}日`, 'cyan'),
      tile('練習した日', `${S.days_practiced}日`, ''));

    // --- calendar (last 20 weeks, columns = weeks, rows = Sun..Sat) ---
    const today = new Date(D.calendar.today + 'T00:00:00');
    const start = new Date(today); start.setDate(start.getDate() - start.getDay() - 7 * 19);
    const cells = [];
    for (let d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) {
      const k = d.toISOString().slice(0, 10), n = D.calendar.days[k] || 0;
      cells.push(el('i', { class: (n >= 6 ? 'l3' : n >= 3 ? 'l2' : n >= 1 ? 'l1' : '') + (k === D.calendar.today ? ' today' : ''), title: `${k}: ${n}回` }));
    }
    for (let i = 0; i < start.getDay(); i++) cells.unshift(el('i', { style: 'visibility:hidden' }));   // first column starts on Sunday
    $('cal').replaceChildren(...cells);
    // the strip is wider than a phone and runs oldest -> newest, so park it on today rather than on 20 weeks ago
    requestAnimationFrame(() => { const w = $('cal').parentElement; w.scrollLeft = w.scrollWidth; });
    $('calNote').textContent = S.n_plays ? '' : 'まだ記録がありません。1曲うたうと色がつきます。';

    // --- per-song section ---
    const songs = D.songs;
    let cur = songs[0]?.song_id;
    function tabs() { $('songtabs').replaceChildren(...songs.map((s) => el('button', { class: cur === s.song_id ? 'on' : '', onclick: () => { cur = s.song_id; tabs(); drawSong(); } }, el('span', { class: 'noruby' }, s.title_jp), ' ', el('span', { class: 'readout accent', style: 'font-size:12px' }, fmtScore(s.best))))); }

    // An SVG with a viewBox scales its text along with everything else: a 520-wide chart squeezed into a 300px
    // phone column rendered 12px labels at 7px. So the viewBox is drawn at the container's own width - one unit
    // per CSS pixel - and re-drawn when that width changes.
    function trendChart(s, CW) {
      const W = Math.max(260, CW), H = W < 380 ? 180 : 220, L = 42, R = 14, T = 14, B = 30;
      const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': '点数の推移' });
      const pts = s.trend.map(([d, sc]) => ({ t: new Date(d).getTime(), sc }));
      const t0 = pts[0].t, t1 = pts[pts.length - 1].t, span = Math.max(t1 - t0, 3600e3);
      const lo = Math.max(0, Math.floor((Math.min(...pts.map((p) => p.sc)) - 5) / 10) * 10), hi = 100;
      const X = (t) => pts.length === 1 ? (L + W - R) / 2 : L + ((t - t0) / span) * (W - L - R);
      const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
      const g = svg('g', { class: 'grid' }), ax = svg('g', { class: 'axis' });
      for (let v = lo; v <= hi; v += (hi - lo) / 5) {
        g.append(svg('line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v) }));
        const tx = svg('text', { x: L - 6, y: Y(v) + 4, 'text-anchor': 'end' }); tx.textContent = Math.round(v); ax.append(tx);
      }
      const d0 = svg('text', { x: L, y: H - 8 }); d0.textContent = fmtDate(pts[0].t, false); ax.append(d0);
      if (pts.length > 1) { const d1 = svg('text', { x: W - R, y: H - 8, 'text-anchor': 'end' }); d1.textContent = fmtDate(pts[pts.length - 1].t, false); ax.append(d1); }
      root.append(g, ax);
      if (pts.length > 1) root.append(svg('path', { class: 'series', d: pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.t).toFixed(1)},${Y(p.sc).toFixed(1)}`).join(' ') }));
      const best = Math.max(...pts.map((p) => p.sc));
      const ch = svg('line', { class: 'crosshair', y1: T, y2: H - B, visibility: 'hidden' }); root.append(ch);
      pts.forEach((p) => {
        const c = svg('circle', { class: 'dot' + (p.sc === best ? ' pb' : ''), cx: X(p.t), cy: Y(p.sc), r: 4 });
        const hit = svg('circle', { cx: X(p.t), cy: Y(p.sc), r: 18, fill: 'transparent' });
        bindTip(hit, () => `<b>${fmtScore(p.sc)}</b><br>${fmtDate(p.t)}${p.sc === best ? ' ★ ベスト' : ''}`,
          () => { ch.setAttribute('x1', X(p.t)); ch.setAttribute('x2', X(p.t)); ch.setAttribute('visibility', 'visible'); },
          () => ch.setAttribute('visibility', 'hidden'));
        root.append(c, hit);
      });
      const lb = svg('text', { x: X(pts.findIndex((p) => p.sc === best) >= 0 ? pts.find((p) => p.sc === best).t : t1), y: Y(best) - 9, 'text-anchor': 'middle', fill: 'var(--accent-t)', 'font-size': 12 }); lb.textContent = fmtScore(best); root.append(lb);
      return root;
    }

    function drawSong() {
      const s = songs.find((x) => x.song_id === cur);
      if (!s) { $('trend').replaceChildren(el('div', { class: 'mute' }, 'まだ記録がありません')); return; }
      $('trend').replaceChildren(trendChart(s, chartWidth($('trend'))));
      const w = D.weak[cur];
      $('heat').replaceChildren(); $('weak').replaceChildren();
      if (!w || !w.all.length) { $('weak').append(el('li', { class: 'mute' }, 'データなし')); return; }
      const byPage = new Map(w.all.map((p) => [p.page, p]));
      for (let pg = 0; pg < w.n_pages; pg++) {
        const p = byPage.get(pg);
        const a = p ? p.acc : null;
        const c = el('i', { style: a == null ? '' : `background:${heatColor(a)}` });
        if (p) bindTip(c, () => `区間 ${pg + 1} · ${fmtT(p.t_start)}–${fmtT(p.t_end)}<br><b>${Math.round(a * 100)}%</b> (${p.n_notes}音)`);
        $('heat').append(c);
      }
      $('weak').replaceChildren(...w.pages.slice(0, 5).map((p) => el('li', {}, el('span', { class: 'pct', style: `color:${heatColor(p.acc)}` }, Math.round(p.acc * 100) + '%'), el('span', {}, `区間 ${p.page + 1}`, el('span', { class: 'dim' }, ` ${fmtT(p.t_start)}–${fmtT(p.t_end)}`)), el('a', { href: `/play?song=${cur}`, class: 'dim', style: 'margin-left:auto;font-size:12px' }, '練習する →'))));
    }

    // --- by-note bar chart ---
    function noteChart(notes, CW) {
      // Every note needs room for its own label, so the chart has a floor of ~26px per note: on a phone it
      // becomes wider than the panel and scrolls sideways instead of shrinking its type into illegibility.
      const n = notes.length;
      const H = 240, L = 40, R = 10, T = 16, B = 46;
      const W = Math.max(260, CW, L + R + n * 26);
      const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': '音ごとの命中率' });
      root.style.width = W + 'px';          // wider than the panel -> .chart scrolls
      root.style.maxWidth = 'none';
      const bw = (W - L - R) / n;
      const Y = (v) => T + (1 - v) * (H - T - B);
      const g = svg('g', { class: 'grid' }), ax = svg('g', { class: 'axis' });
      for (const v of [0, .25, .5, .75, 1]) { g.append(svg('line', { x1: L, x2: W - R, y1: Y(v), y2: Y(v) })); const t = svg('text', { x: L - 6, y: Y(v) + 4, 'text-anchor': 'end' }); t.textContent = Math.round(v * 100) + '%'; ax.append(t); }
      root.append(g, ax);
      const maxN = Math.max(...notes.map((x) => x.n));
      notes.forEach((x, i) => {
        const cx = L + bw * i + bw / 2, w = Math.max(3, Math.min(bw - 3, 22));
        const bar = svg('rect', { class: 'bar', x: cx - w / 2, y: Y(x.hit_rate), width: w, height: Math.max(0, Y(0) - Y(x.hit_rate)), rx: 3, opacity: 0.55 + 0.45 * Math.sqrt(x.n / maxN) });
        const lbl = svg('text', { x: cx, y: H - B + 14, 'text-anchor': 'middle',
          fill: x.midi % 12 === 0 ? 'var(--ink)' : 'var(--ink-dim)', 'font-size': 11 }); lbl.textContent = x.name;
        root.append(bar, lbl);
        if (x.cents != null && Math.abs(x.cents) >= 15) { const a = svg('text', { x: cx, y: H - B + 28, 'text-anchor': 'middle', fill: x.cents > 0 ? 'var(--red-t)' : 'var(--cyan-t)', 'font-size': 12 }); a.textContent = x.cents > 0 ? '↑' : '↓'; root.append(a); }
        const hit = svg('rect', { x: L + bw * i, y: T, width: bw, height: H - T - B, fill: 'transparent' });
        bindTip(hit, () => `${x.name}（${x.name_jp}）<br><b>${Math.round(x.hit_rate * 100)}%</b> 命中 · ${x.n}回<br>${x.cents == null ? '' : (x.cents > 0 ? `+${x.cents}` : x.cents) + ' cents ' + (x.cents > 15 ? '高め↑' : x.cents < -15 ? '低め↓' : 'ちょうど')}`);
        root.append(hit);
      });
      const cap = svg('text', { x: W - R, y: H - 4, 'text-anchor': 'end', fill: 'var(--ink-mute)', 'font-size': 11 }); cap.textContent = '棒の濃さ＝出てきた回数'; root.append(cap);
      return root;
    }
    const drawNotes = () => $('notes').replaceChildren(
      D.by_note.length ? noteChart(D.by_note, chartWidth($('notes'))) : el('div', { class: 'mute' }, 'まだデータがありません'));
    drawNotes();

    // --- recent table ---
    const t = $('recent');
    t.replaceChildren(el('tr', {}, el('th', {}, '曲'), el('th', { class: 'num' }, '点数'), el('th', { class: 'num' }, 'P / G / G / M'), el('th', { class: 'num' }, 'combo'), el('th', {}, 'いつ')),
      ...D.recent.map((p) => el('tr', {}, el('td', {}, el('a', { href: `/play?song=${p.song_id}`, class: 'noruby' }, p.title_jp)), el('td', { class: 'num sc' }, fmtScore(p.score)),
        el('td', { class: 'num dim' }, `${p.n_perfect} / ${p.n_great} / ${p.n_good} / ${p.n_miss}`), el('td', { class: 'num readout' }, p.max_combo), el('td', { class: 'dim', title: fmtDate(p.played_at) }, fmtAgo(p.played_at)))));
    if (!D.recent.length) t.append(el('tr', {}, el('td', { colspan: 5, class: 'mute' }, 'まだ記録がありません。', el('a', { href: '/' }, '1曲うたってみる →'))));
    tabs(); drawSong();

    // Rotating the phone or resizing the window changes how much room the charts have; they are drawn at one
    // SVG unit per CSS pixel, so they have to be re-drawn rather than stretched.
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { drawSong(); drawNotes(); });
    });
    ro.observe($('trend'));
    ro.observe($('notes'));

    return () => { ro.disconnect(); cancelAnimationFrame(raf); hideTip(); };
  },
};
