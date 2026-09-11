// Shared helpers: API calls, current user, nav, avatars, formatting.
'use strict';
import { applyFurigana } from '/static/furigana.js';
export { applyFurigana };

export class ApiError extends Error {
  constructor(status, detail) { super(detail || `HTTP ${status}`); this.status = status; this.detail = detail; }
}

export async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  // A GET the page asked for in its <head> (window.__pf, see the one-line <script> in every page) is already in
  // flight before this module has even loaded; take that response instead of starting a second request. Each
  // entry is consumed once - a later call to the same path, e.g. getMe(true), fetches for real.
  const pre = method === 'GET' && window.__pf && window.__pf[path];
  if (pre) delete window.__pf[path];
  const r = pre ? await pre.catch(() => fetch(path, opts)) : await fetch(path, opts);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new ApiError(r.status, (data && data.detail) || (typeof data === 'string' ? data.slice(0, 200) : r.statusText));
  return data;
}

let _me = null, _meLoaded = false, _dev = false;
// Waiting for /api/me before the header exists is most of what makes a move between pages feel like a page load,
// so the last answer is kept for the tab: renderNav draws from it immediately and corrects itself when the real
// one lands. It is a drawing hint only - every endpoint still checks the cookie.
const ME_CACHE = 'karaoke_me', NAV_CACHE = 'karaoke_nav';
function cachedMe() { try { return JSON.parse(sessionStorage.getItem(ME_CACHE) || 'null'); } catch { return null; } }
function cacheMe(u) {
  try { u ? sessionStorage.setItem(ME_CACHE, JSON.stringify(u)) : sessionStorage.removeItem(ME_CACHE); } catch {}
  if (!u) forgetNav();   // logged out: the next page must not open on this person's header
}
// The finished header's markup, kept for nav-early.js to put back under the next page's <header> before its first
// paint. Saved once the furigana/tooltip passes have settled and again as the page is left (the theme button and
// the active link may have changed since).
function cacheNav(header) { try { sessionStorage.setItem(NAV_CACHE, header.innerHTML); } catch {} }
function forgetNav() { try { sessionStorage.removeItem(NAV_CACHE); } catch {} }
const sameUser = (a, b) => (!a && !b) || !!(a && b && a.id === b.id && a.display_name === b.display_name
  && a.avatar_ver === b.avatar_ver && !!a.is_admin === !!b.is_admin);

export async function getMe(force = false) {
  if (_meLoaded && !force) return _me;
  const d = await api('/api/me');
  _me = d.user; _dev = d.dev_mode; _meLoaded = true;
  cacheMe(_me);
  if (_me) setGuest(false);   // an account outranks the guest flag
  return _me;
}
export function isDevMode() { return _dev; }

export async function requireLogin() {
  const me = await getMe();
  if (!me) {
    location.replace('/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash));
    return new Promise(() => {}); // never resolves; we are navigating away
  }
  return me;
}

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (id) => document.getElementById(id);
export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e[k] = v;
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}

export function avatarUrl(u) {
  return u && u.avatar_ver ? `/avatars/${u.user_id ?? u.id}.webp?v=${u.avatar_ver}` : null;
}
export function avatarEl(u, cls = '') {
  const name = (u && (u.display_name || u.name)) || '?';
  const url = avatarUrl(u);
  if (url) return el('img', { class: `avatar ${cls}`, src: url, alt: name, loading: 'lazy' });
  return el('span', { class: `avatar ${cls}`, title: name }, name.trim().slice(0, 1).toUpperCase());
}

export const fmtScore = (s) => (s === null || s === undefined) ? '--.---' : Number(s).toFixed(3);
export function fmtDate(iso, withTime = true) {
  if (!iso) return '';
  const d = new Date(iso);
  const date = `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
  return withTime ? `${date} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}` : date;
}
export function fmtAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'いま';
  if (s < 3600) return `${Math.floor(s / 60)}分前`;
  if (s < 86400) return `${Math.floor(s / 3600)}時間前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}日前`;
  return fmtDate(iso, false);
}
// Furigana: 漢字《かな》 (Aozora style) -> <ruby>. The base is the run of kanji right before 《, or everything after a ｜.
// With no reading stored it returns the plain text, so callers always pass (song.title_ruby, song.title_jp).
export function rubyEl(marked, plain) {
  if (!marked) return document.createTextNode(plain ?? '');
  const frag = document.createDocumentFragment();
  const re = /(?:｜([^《》｜]+)|([\p{Script=Han}々〆ヶ]+))《([^》]+)》/gu;
  let last = 0, m;
  while ((m = re.exec(marked))) {
    if (m.index > last) frag.append(marked.slice(last, m.index));
    frag.append(el('ruby', {}, m[1] || m[2], el('rt', {}, m[3])));
    last = re.lastIndex;
  }
  if (last < marked.length) frag.append(marked.slice(last));
  return frag;
}
export const fmtDur = (sec) => sec ? `${Math.floor(sec / 60)}:${String(Math.round(sec % 60)).padStart(2, '0')}` : '';

export function grade(s) {
  return s >= 92 ? '殿堂入り!!' : s >= 85 ? 'プロ級!' : s >= 75 ? 'なかなか!' : s >= 60 ? 'まだまだ!' : '練習あるのみ!';
}

const NAV = [
  ['/', 'うたう', 'sing'], ['/stats', 'きろく', 'stats'], ['/leaderboard', 'ランキング', 'ranking'], ['/profile', 'プロフィール', 'profile'],
  ['/about', 'について', 'about'],
];
export async function renderNav(active) {
  const header = document.querySelector('header.top');
  const guess = cachedMe();
  const early = !!header && (guess || isGuest());
  if (early) paintNav(header, guess, active);              // instant: draw the last known answer
  const me = await getMe().catch(() => null);
  if (!header) return me;
  if (!early || !sameUser(guess, me)) paintNav(header, me, active);   // first paint, or: signed out elsewhere, renamed, new avatar
  if (me || isGuest()) {
    setTimeout(() => cacheNav(header), 0);
    addEventListener('pagehide', () => cacheNav(header), { once: true });
  } else forgetNav();   // nobody: the signed-out header is cheap to draw and must not outlive a login
  // Party mode is app-level: while one is live its strip belongs under the header of every page.
  // Loaded lazily - on the pages that own the mode, or anywhere once a party has been started here.
  if (me && (['/', '/songs', '/play'].includes(location.pathname) || localStorage.getItem('karaoke_party'))) {
    import('/static/party.js').then((m) => m.mountStrip()).catch(() => {});
  }
  return me;
}

/** Move the lit link in the header without redrawing it (the app shell, on a move between views). */
export function setNavActive(active) {
  for (const a of document.querySelectorAll('header.top nav.main a')) a.classList.toggle('active', a.getAttribute('href') === active);
}

/** Everything the current header listens to outside itself; aborted the moment the header is redrawn. */
let navLife = null;
function paintNav(header, me, active) {
  navLife?.abort();                          // a repaint throws away the previous header's document listeners
  const ac = navLife = new AbortController();
  const nav = el('nav', { class: 'main' });
  const items = [...NAV];
  if (me && me.is_admin) items.push(['/admin', '管理', 'admin']);
  for (const [href, jp, en] of items) {
    nav.append(el('a', { href, class: href === active ? 'active' : '' }, jp, el('span', { class: 'sub' }, en)));
  }
  // The avatar is a button and everything personal (profile, furigana, theme, logout) drops out of it. A guest
  // gets the same button in the same place - ゲスト instead of a name - so the bar does not change shape when
  // someone plays without an account; only the rows inside differ.
  const chip = el('div', { class: 'userchip' });
  const guest = !me && isGuest();
  if (me) chip.append(userMenu(me));
  else if (guest) chip.append(guestMenu());
  else chip.append(el('a', { href: '/login?next=' + encodeURIComponent(location.pathname + location.search) }, 'ログイン', el('span', { class: 'sub' }, 'login')));
  // Phones: logo + profile stay on the row, the nav folds into a burger menu that drops down under the header.
  const burger = el('button', {
    class: 'burger ghost', 'aria-expanded': 'false', 'aria-label': 'メニュー', title: 'メニュー / menu',
    onclick: () => {
      const open = header.classList.toggle('nav-open');
      burger.setAttribute('aria-expanded', String(open));
    },
  }, '☰');
  document.addEventListener('pointerdown', (e) => {
    if (header.classList.contains('nav-open') && !header.contains(e.target)) burger.click();
  }, { signal: ac.signal });
  // Nobody signed in and not a guest either: there is no menu to hang the settings on, so they stand in the nav.
  if (!me && !guest) nav.append(furiganaButton(), themeButton());
  header.replaceChildren(el('a', { class: 'logo', href: '/', title: 'karaoke.rodeo' }, el('img', { src: '/static/icon-192.png', alt: '' }), 'カラオケ', el('em', {}, '.'), 'ロデオ'), nav, chip, burger);
}

export function toast(text, kind = '') {
  let t = $('toast');
  // Nothing in this app fades: the toast slides up off the bottom edge and drops back down again.
  const DOWN = 'translate(-50%, 200%)', UP = 'translate(-50%, 0)';
  if (!t) {
    t = el('div', { id: 'toast', style: `position:fixed;left:50%;bottom:24px;z-index:50;transform:${DOWN};transition:transform .26s cubic-bezier(.2,1.4,.4,1)` });
    document.body.append(t);
  }
  t.replaceChildren(el('div', { class: `msg ${kind}` }, text));
  requestAnimationFrame(() => (t.style.transform = UP));
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.style.transform = DOWN), 3200);
}

// English sub-labels: <span class="sub">english</span> inside an element -> that element's title tooltip.
export function applySubTooltips(root = document.body) {
  for (const sub of root.querySelectorAll('.sub')) {
    const host = sub.parentElement;
    if (host && !host.title) host.title = sub.textContent.trim();
    sub.remove();
  }
}
if (typeof MutationObserver !== 'undefined') {
  // Both passes rewrite the DOM they walk; a node produced by a pass (ruby/rt) is skipped by both, so this settles.
  const mo = new MutationObserver((muts) => { for (const m of muts) for (const n of m.addedNodes) if (n.nodeType === 1 && n.tagName !== 'RUBY' && n.tagName !== 'RT') { applySubTooltips(n.parentElement || n); applyFurigana(n); } });
  const start = () => { applySubTooltips(); applyFurigana(); mo.observe(document.body, { childList: true, subtree: true }); };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
}

// ---- settings: theme and furigana. Both are pinned on <html> before paint by the one-line script in every
// <head>; these helpers only flip them afterwards and remember the choice. ----
const THEME_KEY = 'karaoke_theme', RUBY_KEY = 'karaoke_furigana';
const remember = (k, v) => { try { localStorage.setItem(k, v); } catch {} };
/** Anything that draws with the palette itself (the note lane canvas) repaints on this. */
const repaint = () => window.dispatchEvent(new Event('karaoke:palette'));

export function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
function isDark() { const t = document.documentElement.dataset.theme; return t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; }
function setDark(on) { const n = on ? 'dark' : 'light'; applyTheme(n); remember(THEME_KEY, n); repaint(); }

const rubyOn = () => document.documentElement.dataset.ruby !== 'off';
function setRuby(on) {
  if (on) delete document.documentElement.dataset.ruby; else document.documentElement.dataset.ruby = 'off';
  remember(RUBY_KEY, on ? 'on' : 'off');
}
export function themeButton() {
  const b = el('button', { class: 'ghost themebtn', type: 'button' });
  const paint = () => { b.textContent = isDark() ? '☀️' : '🌙'; b.title = isDark() ? 'ライトモード / light' : 'ダークモード / dark'; b.setAttribute('aria-label', b.title); };
  b.onclick = () => { setDark(!isDark()); paint(); };
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paint);
  paint();
  return b;
}

/** Signed out there is no profile menu, so furigana gets its own button beside the theme one. */
export function furiganaButton() {
  const b = el('button', { class: 'ghost themebtn rubybtn', type: 'button' }, 'あ');
  const paint = () => {
    b.classList.toggle('off', !rubyOn());
    b.setAttribute('aria-pressed', String(rubyOn()));
    b.title = rubyOn() ? 'ふりがなを消す / furigana off' : 'ふりがなを付ける / furigana on';
    b.setAttribute('aria-label', b.title);
  };
  b.onclick = () => { setRuby(!rubyOn()); paint(); };
  paint();
  return b;
}

/** One row of the profile menu carrying a switch: reads get(), writes through set(). */
function switchItem(icon, jp, en, get, set) {
  const it = el('button', { class: 'mi', type: 'button', role: 'menuitemcheckbox' },
    el('span', { class: 'ico' }, icon), el('span', {}, jp), el('span', { class: 'sub' }, en), el('i', { class: 'sw' }));
  const paint = () => it.setAttribute('aria-checked', String(!!get()));
  it.onclick = (e) => { e.stopPropagation(); set(!get()); paint(); };
  it.addEventListener('repaint', paint);
  paint();
  return it;
}

/** Wire a .userbtn to its .usermenu: opens on click, closes on the next click outside, on Escape, on any link. */
function dropdown(btn, menu) {
  const wrap = el('div', { class: 'usermenu-wrap' }, btn, menu);
  const life = { signal: navLife?.signal };   // dies with the header this menu was drawn into
  const setOpen = (open) => { menu.classList.toggle('open', open); btn.setAttribute('aria-expanded', String(open)); };
  btn.onclick = (e) => { e.stopPropagation(); setOpen(!menu.classList.contains('open')); };
  menu.addEventListener('click', (e) => { if (e.target.closest('a')) setOpen(false); });
  document.addEventListener('pointerdown', (e) => { if (!wrap.contains(e.target)) setOpen(false); }, life);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setOpen(false); }, life);
  // the system flipping to dark while "dark mode" is unpinned must move the switch with it
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    for (const it of menu.querySelectorAll('[role=menuitemcheckbox]')) it.dispatchEvent(new Event('repaint'));
  }, life);
  return wrap;
}

const loginHref = () => '/login?next=' + encodeURIComponent(location.pathname + location.search);

/** Playing without an account: the same button in the same place, with the settings and a way to sign in. */
function guestMenu() {
  const btn = el('button', {
    class: 'userbtn', type: 'button', 'aria-haspopup': 'true', 'aria-expanded': 'false',
    title: 'ゲスト: 点数は保存されません / guest: scores are not saved',
  }, el('span', { class: 'avatar' }, 'ゲ'), el('span', { class: 'nm noruby' }, 'ゲスト'), el('span', { class: 'cv' }, '▾'));
  const menu = el('div', { class: 'usermenu', role: 'menu' },
    el('div', { class: 'head noruby' }, '点数は保存されません', el('span', { class: 'sub' }, 'scores are not saved')),
    switchItem('あ', 'ふりがな', 'furigana', rubyOn, setRuby),
    switchItem('🌙', 'ダークモード', 'dark mode', isDark, setDark),
    el('hr'),
    el('a', { class: 'mi', href: loginHref(), role: 'menuitem' },
      el('span', { class: 'ico' }, '→'), el('span', {}, 'ログイン'), el('span', { class: 'sub' }, 'sign in and keep your scores')));
  return dropdown(btn, menu);
}

/** The avatar button and its drop-down: profile, furigana, dark mode, log out. */
function userMenu(me) {
  const btn = el('button', { class: 'userbtn', type: 'button', 'aria-haspopup': 'true', 'aria-expanded': 'false', title: 'メニュー / menu' },
    avatarEl(me), el('span', { class: 'nm noruby' }, me.display_name), el('span', { class: 'cv' }, '▾'));
  const menu = el('div', { class: 'usermenu', role: 'menu' },
    el('a', { class: 'mi', href: '/profile', role: 'menuitem' },
      el('span', { class: 'ico' }, '👤'), el('span', {}, 'プロフィール'), el('span', { class: 'sub' }, 'profile')),
    el('hr'),
    switchItem('あ', 'ふりがな', 'furigana', rubyOn, setRuby),
    switchItem('🌙', 'ダークモード', 'dark mode', isDark, setDark),
    el('hr'),
    el('button', {
      class: 'mi logout', type: 'button', role: 'menuitem',
      onclick: async () => { cacheMe(null); try { await api('/api/auth/logout', { method: 'POST' }); } finally { location.href = '/'; } },
    }, el('span', { class: 'ico' }, '→'), el('span', {}, 'ログアウト'), el('span', { class: 'sub' }, 'log out')));
  return dropdown(btn, menu);
}

export function qs(name) { return new URLSearchParams(location.search).get(name); }

/** confirm() drawn in the app instead of by the browser: a paper dialog, resolved by its buttons. */
export function confirmDialog({ title, body = '', ok = 'はい', okEn = 'yes', cancel = 'やめる', cancelEn = 'cancel' }) {
  return new Promise((resolve) => {
    const done = (v) => { d.close(); resolve(v); };
    const d = el('dialog', { class: 'confirm' },
      el('h2', {}, title),
      body ? el('p', { class: 'dim' }, body) : null,
      el('div', { class: 'btns' },
        el('button', { class: 'ghost', type: 'button', onclick: () => done(false) }, cancel, el('span', { class: 'sub' }, cancelEn)),
        el('button', { class: 'primary', type: 'button', onclick: () => done(true) }, ok, el('span', { class: 'sub' }, okEn))));
    d.addEventListener('cancel', (e) => { e.preventDefault(); done(false); });   // Esc closes as "no"
    d.addEventListener('close', () => d.remove());
    document.body.append(d);
    d.showModal();
  });
}

// ---- guest mode ----
// "ゲストとして続ける" on the login dialog: the song plays and scores exactly as it does for anyone else, but
// nothing is written to the server - there is no account to write it to. The result dialog says so and offers
// the login that would have kept it. The flag is per-browser and is dropped the moment someone signs in.
const GUEST_KEY = 'karaoke_guest';
export const isGuest = () => { try { return localStorage.getItem(GUEST_KEY) === '1'; } catch { return false; } };
export function setGuest(on) { try { on ? localStorage.setItem(GUEST_KEY, '1') : localStorage.removeItem(GUEST_KEY); } catch {} }
/** Signed-out pages that draw their own header (the landing) hang the guest menu here. */
export function guestChip() { return guestMenu(); }
