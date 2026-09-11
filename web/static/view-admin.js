// 管理 - queue a song, watch the worker, publish, reprocess, edit titles and readings.
import { api, el, $, fmtAgo, fmtDur, toast } from '/static/common.js';

const STATUS = { processing: '処理中', labeling: 'ラベリング待ち', published: '公開中', failed: '失敗', hidden: '非公開' };
const STAGE = { download: 'ダウンロード', extract: '抽出 (extract)', geotime: 'タイミング (geotime)', anchor: '音程アンカー', lyrics: '歌詞', finalize: '仕上げ' };

export default {
  title: '管理',
  auth: 'admin',
  load: () => api('/api/admin/songs'),

  render(main, first) {
    main.innerHTML = `
  <div class="stack" style="gap:16px">
  <h1>管理 <span class="sub">admin</span></h1>
  <section class="panel">
    <h2>曲を追加 <span class="sub">add a song</span></h2>
    <p class="dim" style="font-size:12px;line-height:1.6;margin:0 0 10px">カラオケ@DIVA の動画URLを貼ると、ワーカーが 720p でダウンロード → 音符・タイミング抽出 → 音程アンカー → 歌詞領域を処理します（Pi では30〜60分）。終わると「ラベリング待ち」になり、ラベラーで仕上げてから公開します。</p>
    <form class="add" id="add"><input id="url" type="url" required placeholder="https://www.youtube.com/watch?v=…"><button class="primary" type="submit">追加 <span class="sub">queue</span></button></form>
    <div id="addMsg" style="margin-top:8px"></div>
    <div class="worker dim" id="worker" style="margin-top:8px"></div>
  </section>
  <section class="panel tablewrap">
    <h2>曲 <span class="sub">songs</span></h2>
    <table id="tbl"></table>
  </section>
  <section class="panel" id="logSec" hidden>
    <div class="row spread"><h2 id="logTitle">ログ</h2><button class="small ghost" id="logClose">閉じる</button></div>
    <pre class="log" id="log"></pre>
  </section>
  </div>`;

    let logJob = null;
    async function act(path, method = 'POST', body) { try { await api(path, { method, body }); await load(); } catch (e) { toast(e.message, 'err'); } }
    function statusCell(s) {
      const j = s.job;
      const parts = [el('span', { class: `pill ${s.status}` }, STATUS[s.status] || s.status)];
      if (j && (j.status === 'running' || j.status === 'queued')) {
        parts.push(el('div', { style: 'margin-top:4px;font-size:12px' }, j.status === 'queued' ? '順番待ち' : `${STAGE[j.stage] || j.stage || ''} `, el('span', { class: 'prog' }, el('i', { style: `width:${Math.round((j.progress || 0) * 100)}%` })), ` ${Math.round((j.progress || 0) * 100)}%`,
          j.heartbeat_at ? el('span', { class: 'mute' }, ` · ${fmtAgo(j.heartbeat_at)}`) : ''));
      }
      if (s.status === 'labeling') parts.push(el('div', { class: 'ready', style: 'margin-top:4px;font-size:12px' }, '★ ラベリングできます'));
      if (j && j.status === 'failed') parts.push(el('div', { class: 'red', style: 'margin-top:4px;font-size:12px' }, j.error || 'failed'));
      return el('td', {}, ...parts);
    }
    function actions(s) {
      const j = s.job, busy = j && (j.status === 'running' || j.status === 'queued');
      const a = [];
      if (s.has_map && s.has_video) a.push(el('a', { href: `/label#${s.id}/1`, target: '_blank' }, el('button', { class: 'small' }, 'ラベラー ↗')));
      if (s.status === 'labeling' || s.status === 'hidden') a.push(el('button', { class: 'small primary', style: 'padding:4px 12px;font-size:12px', onclick: () => act(`/api/admin/songs/${s.id}/publish`) }, '公開'));
      if (s.status === 'published') a.push(el('button', { class: 'small warn', onclick: () => act(`/api/admin/songs/${s.id}/unpublish`) }, '非公開に'));
      if (s.status === 'published') a.push(el('a', { href: `/play?song=${s.id}`, target: '_blank' }, el('button', { class: 'small ghost' }, 'うたう ↗')));
      if (j) a.push(el('button', { class: 'small ghost', onclick: () => showLog(j.id, s) }, 'ログ'));
      if (busy) a.push(el('button', { class: 'small danger', onclick: () => act(`/api/admin/jobs/${j.id}/cancel`) }, '中止'));
      else {
        const sel = el('select', { style: 'font-size:12px;padding:3px 6px' }, el('option', { value: '' }, '再処理…'), el('option', { value: 'all' }, s.has_video ? '全部（動画は再利用）' : '全部（再ダウンロード）'),
          el('option', { value: 'extract' }, 'extract から'), el('option', { value: 'geotime' }, 'geotime から'), el('option', { value: 'anchor' }, 'anchor から'), el('option', { value: 'lyrics' }, 'lyrics のみ'));
        sel.onchange = () => { if (!sel.value) return; if (s.has_map && !confirm('いまの song map（手作業ラベル含む）を上書きします。続けますか？')) { sel.value = ''; return; } act(`/api/admin/songs/${s.id}/reprocess`, 'POST', { from_stage: sel.value === 'all' ? null : sel.value }); };
        a.push(sel);
        a.push(el('button', { class: 'small danger ghost', onclick: () => { if (confirm(`「${s.title_jp || s.id}」を削除します。記録も消えます。ファイルも消しますか？（OK=ファイルも消す / キャンセル=残す）`)) act(`/api/admin/songs/${s.id}?purge=1`, 'DELETE'); else if (confirm('DBだけ削除しますか？')) act(`/api/admin/songs/${s.id}`, 'DELETE'); } }, '削除'));
      }
      return el('td', {}, el('div', { class: 'acts' }, ...a));
    }
    function titleCell(s) {
      const t = el('input', { type: 'text', value: s.title_jp || '', placeholder: '曲名' }), ar = el('input', { type: 'text', value: s.artist_jp || '', placeholder: 'アーティスト' });
      // furigana for the menu, written 漢字《かな》 - e.g. 夜《よる》に駆《か》ける
      const tr = el('input', { type: 'text', value: s.title_ruby || '', placeholder: 'ふりがな 例: 夜《よる》に駆《か》ける', title: '曲名のふりがな（漢字《かな》）' });
      const arr = el('input', { type: 'text', value: s.artist_ruby || '', placeholder: 'アーティストのふりがな', title: 'アーティストのふりがな（漢字《かな》）' });
      const save = async () => {
        const body = {};
        if (t.value !== (s.title_jp || '')) body.title_jp = t.value;
        if (ar.value !== (s.artist_jp || '')) body.artist_jp = ar.value;
        if (tr.value !== (s.title_ruby || '')) body.title_ruby = tr.value;
        if (arr.value !== (s.artist_ruby || '')) body.artist_ruby = arr.value;
        if (Object.keys(body).length) await act(`/api/admin/songs/${s.id}`, 'PATCH', body);
      };
      t.onblur = ar.onblur = tr.onblur = arr.onblur = save;
      return el('td', { class: 'title' }, t, el('div', { style: 'height:4px' }), tr, el('div', { style: 'height:4px' }), ar, el('div', { style: 'height:4px' }), arr, el('div', { class: 'mute', style: 'font-size:11px;margin-top:3px' }, s.id, s.youtube_url ? ' · ' : '', s.youtube_url ? el('a', { href: s.youtube_url, target: '_blank' }, 'YouTube ↗') : ''));
    }
    function paint(d) {
      const tbl = $('tbl');
      if (!tbl) return;   // the view was left while a refresh was in flight
      tbl.replaceChildren(el('tr', {}, el('th', {}, '曲'), el('th', {}, '状態'), el('th', { class: 'num' }, '音数 / 区間'), el('th', {}, 'map'), el('th', {}, '操作')),
        ...d.songs.map((s) => el('tr', {}, titleCell(s), statusCell(s), el('td', { class: 'num' }, s.n_notes != null ? `${s.n_notes} / ${s.n_pages}` : '-', el('br'), el('small', { class: 'mute' }, fmtDur(s.duration))),
          el('td', { class: 'dim', style: 'font-size:12px' }, s.method || '', s.n_manual ? el('br') : '', s.n_manual ? `手作業 ${s.n_manual}` : ''), actions(s))));
      const running = d.queue.find((q) => q.status === 'running');
      const hb = running && d.songs.find((s) => s.id === running.song_id)?.job?.heartbeat_at;
      const stale = hb && Date.now() - new Date(hb).getTime() > 120e3;
      $('worker').textContent = d.queue.length ? `キュー: ${d.queue.length}件${running ? ` · 実行中 ${running.song_id} (${STAGE[running.stage] || running.stage || '…'})` : ' · ワーカー待ち'}` + (stale ? ' ⚠ ワーカーからの応答が2分以上ありません（worker.py は動いていますか？）' : '') : 'キューは空です';
      if (logJob) refreshLog();
    }
    async function load() { paint(await api('/api/admin/songs')); }
    async function showLog(jid, s) { logJob = jid; $('logSec').hidden = false; $('logTitle').textContent = `ログ - ${s.title_jp || s.id}`; await refreshLog(); $('logSec').scrollIntoView({ behavior: 'smooth' }); }
    async function refreshLog() {
      try { const j = await api(`/api/admin/jobs/${logJob}`); const log = $('log'); if (!log) return; log.textContent = `[${j.status}] ${j.stage || ''} ${j.error ? 'error: ' + j.error : ''}\n` + (j.log || ''); if (j.status === 'running') log.scrollTop = log.scrollHeight; }
      catch (e) { const log = $('log'); if (log) log.textContent = e.message; }
    }
    $('logClose').onclick = () => { logJob = null; $('logSec').hidden = true; };
    $('add').onsubmit = async (e) => {
      e.preventDefault();
      $('addMsg').replaceChildren();
      try { const r = await api('/api/admin/songs', { method: 'POST', body: { url: $('url').value } }); $('addMsg').append(el('div', { class: 'msg ok' }, `キューに入れました: ${r.song.id}`)); $('url').value = ''; await load(); }
      catch (err) { $('addMsg').append(el('div', { class: 'msg err' }, err.message)); }
    };
    paint(first);
    const timer = setInterval(() => load().catch(() => {}), 5000);
    return () => { clearInterval(timer); logJob = null; };
  },
};
