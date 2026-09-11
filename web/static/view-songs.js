// うたう - the catalogue. Party mode is started here and only here; while it runs, the strip under the header
// carries it on every view.
import { api, el, avatarEl, fmtScore, fmtAgo, fmtDur, rubyEl, toast, $ } from '/static/common.js';
import { onParty, startParty, mountStrip } from '/static/party.js';

export default {
  title: 'うたう',
  load: () => Promise.all([api('/api/songs'), api('/api/leaderboard').catch(() => ({ recent: [] }))]),

  render(main, [{ songs }, lb], { me, guest }) {
    main.innerHTML = `
  <div id="welcome" class="welcome" hidden>
    <h1 class="logo" style="font-size:30px" title="karaoke.rodeo">カラオケ<em>.</em>ロデオ</h1>
    <p>カラオケ@DIVA の練習動画で、家でひとり採点カラオケ。マイクの音程を音符バーと比べて、カラオケ機みたいに点数が出ます。
      ログインすると点数の履歴・上達グラフ・ランキングが残ります。</p>
    <a href="/login"><button class="primary">ログイン / はじめる <span class="sub">sign in</span></button></a>
    <p id="guestNote" class="dim" style="margin-top:10px;font-size:13px" hidden>いまはゲストです。曲はそのまま歌えますが、点数は保存されません。
      <span class="sub">You are a guest: songs play, scores are not saved.</span></p>
  </div>
  <div class="hero">
    <div><h1>曲をえらぶ <span class="sub">choose a song</span></h1></div>
    <div class="row">
      <input id="q" type="text" placeholder="曲名・アーティストで検索" style="min-width:240px">
      <button id="partyBtn" class="party" hidden>🎉 パーティー <span class="sub">start a party</span></button>
    </div>
  </div>
  <div class="two">
    <div id="songs" class="grid cards"></div>
    <aside class="panel recent">
      <h3>みんなの最近 <span class="sub">recent</span></h3>
      <ul id="recent"></ul>
    </aside>
  </div>`;
    if (!me) { $('welcome').hidden = false; $('guestNote').hidden = !guest; }

    let offParty = null;
    if (me) {
      $('partyBtn').hidden = false;
      mountStrip();
      offParty = onParty((p) => {
        $('partyBtn').disabled = !!p;
        $('partyBtn').textContent = p ? `🎉 パーティー ${p.code}` : '🎉 パーティー';
      });
      $('partyBtn').onclick = async () => {
        $('partyBtn').disabled = true;
        try { await startParty(); toast('パーティーを始めました。スマホでQRを読んで参加してもらおう。', 'ok'); }
        catch (e) { toast(e.message, 'err'); $('partyBtn').disabled = false; }
      };
    }

    function card(s) {
      const thumb = el('div', { class: 'thumb' });
      if (s.has_thumb) thumb.append(el('img', { src: `/api/songs/${s.id}/thumb`, alt: '' }));
      const top = s.top && s.top[0];
      return el('a', { class: 'song', href: (me || guest) ? `/play?song=${encodeURIComponent(s.id)}` : '/login?next=' + encodeURIComponent(`/play?song=${s.id}`) },
        thumb,
        el('div', { class: 'body' },
          el('div', { class: 'title noruby' }, rubyEl(s.title_ruby, s.title_jp || s.title_en || s.id)),
          el('div', { class: 'artist noruby' }, rubyEl(s.artist_ruby, s.artist_jp || s.artist_en || '')),
          el('div', { class: 'meta' },
            el('span', {}, `${s.n_notes ?? '?'}音 · ${fmtDur(s.duration)}` + (s.my_plays ? ` · ${s.my_plays}回` : '')),
            top ? el('span', { class: 'top', title: `1位 ${top.display_name}` }, avatarEl(top), el('span', { class: 'readout accent' }, fmtScore(top.best))) : el('span', { class: 'mute' }, 'まだ記録なし'))));
    }
    function draw(filter = '') {
      const f = filter.trim().toLowerCase();
      const list = songs.filter((s) => !f || [s.title_jp, s.artist_jp, s.title_en, s.artist_en].some((x) => (x || '').toLowerCase().includes(f)));
      $('songs').replaceChildren(...list.map(card));
      if (!list.length) $('songs').append(el('div', { class: 'panel dim' }, songs.length ? '見つかりません' : 'まだ曲がありません。管理画面から追加してください。'));
    }
    draw();
    $('q').oninput = () => draw($('q').value);
    $('recent').replaceChildren(...(lb.recent || []).slice(0, 12).map((r) =>
      el('li', {}, avatarEl(r), el('span', {}, el('b', { class: 'noruby' }, r.display_name), ' ', el('span', { class: 'dim noruby' }, r.title_jp), el('br'), el('small', { class: 'mute' }, fmtAgo(r.played_at))),
        el('span', { class: 's' }, fmtScore(r.score)))));
    if (!(lb.recent || []).length) $('recent').append(el('li', { class: 'mute' }, 'まだ誰もうたっていません'));

    return () => { offParty?.(); };
  },
};
