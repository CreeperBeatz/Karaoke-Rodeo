// ランキング - 総合 (average of per-song bests) and 曲別 (a searchable song picker, then that song's board).
import { api, el, $, avatarEl, fmtScore, fmtAgo } from '/static/common.js';

export default {
  title: 'ランキング',
  load: () => api('/api/songs'),

  render(main, { songs }, { params }) {
    main.innerHTML = `
  <h1>ランキング <span class="sub">leaderboard</span></h1>
  <div class="tabs" id="tabs"></div>

  <section id="overall" hidden>
    <div class="panel tablewrap"><table id="tbl"></table></div>
    <p class="dim" style="font-size:12px">総合 = 歌った曲ごとの自己ベストの平均。完走した記録のみ。ゲストの記録はパーティー内にだけ残ります。</p>
  </section>

  <section id="picker" hidden>
    <div class="search">
      <input id="q" type="text" placeholder="曲名・アーティストで検索" autocomplete="off">
      <span class="n" id="qn"></span>
    </div>
    <div class="songlist" id="songlist"></div>
  </section>

  <section id="songboard" hidden>
    <div class="crumb">
      <button class="ghost small" id="back">← 曲をえらぶ</button>
      <h2 id="sbTitle"></h2><span class="dim" id="sbArtist"></span>
    </div>
    <div class="panel tablewrap"><table id="sbTbl"></table></div>
    <p class="dim" style="font-size:12px">この曲の自己ベスト順。完走した記録のみ。</p>
  </section>`;

    const byId = new Map(songs.map((s) => [s.id, s]));
    const name = (s) => s.title_jp || s.title_en || s.id;

    let tab = params.get('song') !== null ? 'song' : 'all';   // 'all' | 'song'  (?song= with no id = the picker)
    let cur = params.get('song') || null;                     // selected song id in the 曲別 tab

    function tabs() {
      $('tabs').replaceChildren(
        el('button', { class: tab === 'all' ? 'on' : '', onclick: () => go('all', null) }, '総合 ', el('span', { class: 'sub' }, 'overall')),
        el('button', { class: tab === 'song' ? 'on' : '', onclick: () => go('song', cur) }, '曲別 ', el('span', { class: 'sub' }, 'by song')));
    }
    function url() { return tab === 'song' && cur ? `/leaderboard?song=${encodeURIComponent(cur)}` : tab === 'song' ? '/leaderboard?song=' : '/leaderboard'; }
    async function go(t, song) {
      tab = t; cur = song;
      history.replaceState(history.state, '', url());   // the tab lives in the URL, but is not a page of its own
      tabs();
      $('overall').hidden = tab !== 'all';
      $('picker').hidden = !(tab === 'song' && !cur);
      $('songboard').hidden = !(tab === 'song' && cur);
      if (tab === 'all') await loadOverall();
      else if (cur) await loadSong(cur);
      else { renderList(); $('q').focus(); }
    }

    function who(r) { return el('td', {}, avatarEl(r), el('span', { class: 'noruby' }, r.display_name)); }
    function rk(i) { return el('td', { class: `rk rank${i}` }, i <= 3 ? ['🥇', '🥈', '🥉'][i - 1] : i); }

    async function loadOverall() {
      const { board } = await api('/api/leaderboard');
      const t = $('tbl');
      if (!t) return;   // the view was left while the board was loading
      t.replaceChildren(el('tr', {}, el('th', {}, '#'), el('th', {}, 'うたい手'), el('th', { class: 'num' }, '平均ベスト'), el('th', { class: 'num' }, '最高'), el('th', { class: 'num' }, '曲数'), el('th', { class: 'num' }, '回数')),
        ...board.map((r) => el('tr', { class: r.me ? 'me' : '' }, rk(r.rank), who(r), el('td', { class: 'num sc' }, fmtScore(r.avg_best)), el('td', { class: 'num readout' }, fmtScore(r.top)), el('td', { class: 'num' }, r.n_songs), el('td', { class: 'num' }, r.n_plays))));
      if (!board.length) t.append(el('tr', {}, el('td', { class: 'mute', colspan: 6 }, 'まだ記録がありません')));
    }

    function renderList(filter = '') {
      const f = filter.trim().toLowerCase();
      const list = songs.filter((s) => !f || [s.title_jp, s.artist_jp, s.title_en, s.artist_en].some((x) => (x || '').toLowerCase().includes(f)));
      $('qn').textContent = f ? `${list.length} / ${songs.length} 曲` : `${songs.length} 曲`;
      $('songlist').replaceChildren(...list.map((s) => {
        const top = s.top && s.top[0];
        return el('button', { class: 'songrow', onclick: () => go('song', s.id) },
          el('span', { class: 'tt noruby' }, el('b', {}, name(s)), el('span', {}, s.artist_jp || s.artist_en || '')),
          s.my_best != null ? el('span', { class: 'mine', title: '自己ベスト' }, fmtScore(s.my_best)) : null,
          top ? el('span', { class: 'top1', title: `1位 ${top.display_name}` }, avatarEl(top), fmtScore(top.best))
              : el('span', { class: 'mute', style: 'font-size:12px' }, 'まだ記録なし'));
      }));
      if (!list.length) $('songlist').append(el('div', { class: 'panel dim' }, songs.length ? '見つかりません' : 'まだ曲がありません'));
    }

    async function loadSong(id) {
      const s = byId.get(id);
      $('sbTitle').textContent = s ? name(s) : id;
      $('sbArtist').textContent = s ? (s.artist_jp || s.artist_en || '') : '';
      const t = $('sbTbl');
      t.replaceChildren(el('tr', {}, el('td', { class: 'mute' }, '読み込み中…')));
      const { board } = await api(`/api/songs/${encodeURIComponent(id)}/leaderboard`);
      if (!t.isConnected) return;
      t.replaceChildren(el('tr', {}, el('th', {}, '#'), el('th', {}, 'うたい手'), el('th', { class: 'num' }, 'ベスト'), el('th', { class: 'num' }, '回数'), el('th', {}, '最後に歌った')),
        ...board.map((r) => el('tr', { class: r.me ? 'me' : '' }, rk(r.rank), who(r), el('td', { class: 'num sc' }, fmtScore(r.best)), el('td', { class: 'num' }, r.n), el('td', { class: 'dim' }, fmtAgo(r.last)))));
      if (!board.length) t.append(el('tr', {}, el('td', { class: 'mute', colspan: 5 }, 'まだ誰も歌っていません。一番乗りしよう！')));
    }

    $('q').oninput = () => renderList($('q').value);
    $('back').onclick = () => go('song', null);
    go(tab, cur);
  },
};
