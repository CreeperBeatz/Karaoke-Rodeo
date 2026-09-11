// Shared helpers: API calls, current user, nav, avatars, formatting.
'use strict';

export class ApiError extends Error {
  constructor(status, detail) { super(detail || `HTTP ${status}`); this.status = status; this.detail = detail; }
}

export async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new ApiError(r.status, (data && data.detail) || (typeof data === 'string' ? data.slice(0, 200) : r.statusText));
  return data;
}

let _me = null, _meLoaded = false, _dev = false;
export async function getMe(force = false) {
  if (_meLoaded && !force) return _me;
  const d = await api('/api/me');
  _me = d.user; _dev = d.dev_mode; _meLoaded = true;
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
export const fmtDur = (sec) => sec ? `${Math.floor(sec / 60)}:${String(Math.round(sec % 60)).padStart(2, '0')}` : '';

export function grade(s) {
  return s >= 92 ? '殿堂入り!!' : s >= 85 ? 'プロ級!' : s >= 75 ? 'なかなか!' : s >= 60 ? 'まだまだ!' : '練習あるのみ!';
}

const NAV = [
  ['/', 'うたう', 'sing'], ['/stats', 'きろく', 'stats'], ['/leaderboard', 'ランキング', 'ranking'], ['/profile', 'プロフィール', 'profile'],
  ['/about', 'について', 'about'],
];
export async function renderNav(active) {
  const me = await getMe().catch(() => null);
  const header = document.querySelector('header.top');
  if (!header) return me;
  const nav = el('nav', { class: 'main' });
  const items = [...NAV];
  if (me && me.is_admin) items.push(['/admin', '管理', 'admin']);
  for (const [href, jp, en] of items) {
    nav.append(el('a', { href, class: href === active ? 'active' : '' }, jp, el('span', { class: 'sub' }, en)));
  }
  const chip = el('div', { class: 'userchip' });
  if (me) chip.append(el('a', { href: '/profile', class: 'row', style: 'gap:8px' }, avatarEl(me), el('span', {}, me.display_name)));
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
  });
  header.replaceChildren(el('a', { class: 'logo', href: '/', title: 'karaoke.rodeo' }, 'カラオケ', el('em', {}, '.'), 'ロデオ'), nav, chip, burger);
  // Party mode is app-level: while one is live its strip belongs under the header of every page.
  // Loaded lazily — on the pages that own the mode, or anywhere once a party has been started here.
  if (me && (['/', '/play'].includes(location.pathname) || localStorage.getItem('karaoke_party'))) {
    import('/static/party.js').then((m) => m.mountStrip()).catch(() => {});
  }
  return me;
}

export function toast(text, kind = '') {
  let t = $('toast');
  if (!t) { t = el('div', { id: 'toast', style: 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:50;transition:opacity .3s' }); document.body.append(t); }
  t.replaceChildren(el('div', { class: `msg ${kind}` }, text));
  t.style.opacity = 1;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.style.opacity = 0), 3200);
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
  const mo = new MutationObserver((muts) => { for (const m of muts) for (const n of m.addedNodes) if (n.nodeType === 1) applySubTooltips(n.parentElement || n); });
  const start = () => { applySubTooltips(); mo.observe(document.body, { childList: true, subtree: true }); };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
}

export function qs(name) { return new URLSearchParams(location.search).get(name); }
