// プロフィール - name, photo, mic latency; install as an app; log out.
import { api, renderNav, el, $, avatarEl, toast, getMe } from '/static/common.js';

export default {
  title: 'プロフィール',
  auth: true,

  render(main, _data, { me: me0, params, navigate }) {
    let me = me0;
    main.innerHTML = `
  <div class="box stack" style="gap:16px">
    <div id="welcome" class="msg ok" hidden>ようこそ！ 名前と写真を決めてください。</div>
    <section class="panel">
      <h2>プロフィール <span class="sub">profile</span></h2>
      <div class="avwrap">
        <div id="av"></div>
        <div class="stack">
          <div class="actions">
            <button id="pick">写真をえらぶ <span class="sub">upload</span></button>
            <button id="rm" class="ghost small" hidden>写真を消す</button>
          </div>
          <div class="hint">JPEG / PNG / WebP、4MBまで。正方形に切り抜かれます。</div>
          <input id="file" type="file" accept="image/*">
        </div>
      </div>
      <form id="f" class="stack" style="margin-top:18px">
        <label class="field">表示名 <span class="sub">display name</span><input id="name" type="text" maxlength="24" required></label>
        <label class="field">メール <span class="sub">email</span><input id="email" type="email" disabled></label>
        <label class="field">マイク遅延補正 <span class="sub">mic latency (ms)</span>
          <div class="row"><input id="lat" type="range" min="0" max="400" step="10" style="flex:1"><output id="latOut" class="readout"></output></div>
          <span class="hint">歌っているのに少し遅れて判定される時は上げる。だいたい 100〜200ms。プレイ画面でも変えられます。</span></label>
        <div class="row spread"><button class="primary" type="submit">保存 <span class="sub">save</span></button><span id="saved" class="green"></span></div>
      </form>
    </section>
    <section class="panel row spread" id="installSec">
      <div class="stack" style="gap:4px">
        <b>アプリとして使う <span class="sub">install as an app</span></b>
        <span class="hint" id="installHint">ホーム画面に追加すると、全画面でアプリのように開けます。</span>
      </div>
      <button id="install" class="primary">ホーム画面に追加 <span class="sub">add to home screen</span></button>
    </section>
    <section class="panel row spread">
      <span class="dim">このブラウザからログアウト</span>
      <button id="logout" class="ghost">ログアウト <span class="sub">logout</span></button>
    </section>
  </div>
  <dialog id="installDlg" class="install">
    <h3 style="margin:0">ホーム画面に追加 <span class="sub">add to home screen</span></h3>
    <ol id="installSteps"></ol>
    <div class="row" style="justify-content:flex-end;margin-top:18px"><button id="installClose">閉じる <span class="sub">close</span></button></div>
  </dialog>`;

    if (params.get('welcome')) $('welcome').hidden = false;
    const draw = () => { $('av').replaceChildren(avatarEl(me, 'xl')); $('rm').hidden = !me.avatar_ver; };
    draw();
    $('name').value = me.display_name; $('email').value = me.email;
    $('lat').value = me.latency_ms; $('latOut').textContent = me.latency_ms + 'ms';
    $('lat').oninput = () => ($('latOut').textContent = $('lat').value + 'ms');
    $('pick').onclick = () => $('file').click();
    $('av').onclick = () => $('file').click();
    $('file').onchange = async () => {
      const f = $('file').files[0];
      if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      try {
        const r = await api('/api/me/avatar', { method: 'POST', form: fd });
        me.avatar_ver = r.avatar_ver; draw(); toast('写真を更新しました', 'ok'); await getMe(true); renderNav('/profile');
      } catch (e) { toast(e.message, 'err'); }
      $('file').value = '';
    };
    $('rm').onclick = async () => { await api('/api/me/avatar', { method: 'DELETE' }); me.avatar_ver = 0; draw(); await getMe(true); renderNav('/profile'); };
    $('f').onsubmit = async (e) => {
      e.preventDefault();
      try {
        const r = await api('/api/me', { method: 'PATCH', body: { display_name: $('name').value, latency_ms: Number($('lat').value) } });
        me = { ...me, ...r.user }; $('saved').textContent = '保存しました ✓'; setTimeout(() => { const s = $('saved'); if (s) s.textContent = ''; }, 2500);
        localStorage.setItem('karaoke_latency', me.latency_ms);
        await getMe(true); renderNav('/profile');
        const next = params.get('next'); if (params.get('welcome') && next) navigate(next);
      } catch (err) { toast(err.message, 'err'); }
    };
    $('logout').onclick = async () => { await api('/api/auth/logout', { method: 'POST' }); location.href = '/'; };

    // ---- install as an app ----
    // Android/desktop Chromium: the captured beforeinstallprompt shows the native install sheet.
    // iOS has no install API: Safari (and, since iOS 16.4, Chrome/Firefox) add to the home screen from the share sheet.
    const ua = navigator.userAgent;
    const isIOS = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const isAndroid = /Android/.test(ua);
    const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
    const markInstalled = () => { const b = $('install'); if (!b) return; b.hidden = true; $('installHint').textContent = 'アプリとして開いています ✓'; };
    if (standalone) markInstalled();
    window.addEventListener('appinstalled', markInstalled);
    const li = (...c) => el('li', {}, ...c);
    const ico = (t) => el('span', { class: 'ico' }, t);
    function showSteps() {
      const steps = isIOS
        ? [li('Safari の下（iPad は上）の 共有ボタン ', ico('⎙'), ' をタップ'), li('「ホーム画面に追加」を選ぶ'), li('右上の「追加」をタップ')]
        : isAndroid
        ? [li('Chrome の右上メニュー ', ico('⋮'), ' をタップ'), li('「ホーム画面に追加」または「アプリをインストール」を選ぶ'), li('「インストール」をタップ')]
        : [li('ブラウザのアドレスバー右端のインストールアイコン、またはメニューの「アプリをインストール」を選ぶ')];
      $('installSteps').replaceChildren(...steps);
      $('installDlg').showModal();
    }
    $('installClose').onclick = () => $('installDlg').close();
    $('install').onclick = async () => {
      const p = window.__installPrompt;
      if (!p) return showSteps();
      p.prompt();
      const { outcome } = await p.userChoice;
      window.__installPrompt = null;
      if (outcome === 'accepted') markInstalled();
    };

    return () => window.removeEventListener('appinstalled', markInstalled);
  },
};
