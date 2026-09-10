// Party mode as an app-level mode: started from the home page, then a strip rides along on every page
// until the host ends it.  Owns the party state, the polling, and the strip UI; the play page asks it
// who is singing (and in which colour).
import { api, el, $, avatarEl, fmtScore, toast } from '/static/common.js';

const LS = 'karaoke_party';           // remembers a live party so the strip mounts on every page
const POLL_MS = 3000;

let party = null;                     // last known state, or null when no party is live
let timer = null, mounted = false, loading = null;
const listeners = new Set();

export const partyLive = () => party && !party.ended ? party : null;
export const partyRemembered = () => localStorage.getItem(LS);
export function onParty(fn) { listeners.add(fn); fn(partyLive()); return () => listeners.delete(fn); }

function publish() {
  if (party && party.ended) party = null;
  if (party) localStorage.setItem(LS, party.code); else localStorage.removeItem(LS);
  for (const fn of listeners) { try { fn(partyLive()); } catch (e) { console.error(e); } }
  renderStrip();
}

/** The member currently holding the mic (null when no party). */
export function currentSinger() {
  if (!party) return null;
  return party.members.find((m) => m.id === party.current_member_id) || null;
}

export async function loadParty(force = false) {
  if (loading && !force) return loading;
  loading = (async () => {
    try {
      const s = await api('/api/party/mine');
      party = s && s.code && !s.ended ? s : null;
    } catch (e) { party = null; }        // not logged in / transient
    publish();
    return party;
  })();
  try { return await loading; } finally { loading = null; }
}

export async function startParty() {
  party = await api('/api/party', { method: 'POST' });
  publish();
  poll(true);
  return party;
}

export async function endParty() {
  if (!party) return;
  await api(`/api/party/${party.code}/end`, { method: 'POST' }).catch(() => {});
  party = null;
  publish();
  poll(false);
}

export async function setSinger(memberId) {
  if (!party) return;
  try { party = await api(`/api/party/${party.code}/singer`, { method: 'POST', body: { member_id: memberId } }); publish(); }
  catch (e) { toast(e.message, 'err'); }
}

/** Called after a play is saved so the strip's bests refresh straight away. */
export async function refreshParty() {
  if (!party) return;
  try { party = await api(`/api/party/${party.code}`); publish(); } catch (e) { /* transient */ }
}

function poll(on) {
  clearInterval(timer); timer = null;
  if (on && !document.hidden) timer = setInterval(refreshParty, POLL_MS);
}
document.addEventListener('visibilitychange', () => poll(!!party));

// ---- strip ----
export async function mountStrip() {
  if (mounted) { renderStrip(); return; }
  mounted = true;
  await loadParty();
  poll(!!party);
}

function stripEl() {
  let s = $('partystrip');
  if (!s) {
    s = el('div', { id: 'partystrip', class: 'partystrip' });
    const header = document.querySelector('header.top');
    if (!header || !header.parentNode) return null;
    header.after(s);
  }
  return s;
}

function renderStrip() {
  const s = stripEl();
  if (!s) return;
  const p = partyLive();
  if (!p) { s.hidden = true; s.replaceChildren(); document.body.classList.remove('has-party'); return; }
  s.hidden = false;
  document.body.classList.add('has-party');
  const queue = p.members.filter((m) => m.queue_pos != null).sort((a, b) => a.queue_pos - b.queue_pos).map((m) => m.id);
  s.replaceChildren(
    el('span', { class: 'pl' }, '🎉 パーティー'),
    el('span', { class: 'pcode', title: p.join_url }, p.code),
    el('div', { class: 'pmembers' }, ...p.members.map((m) => el('button', {
      class: 'pmember' + (m.id === p.current_member_id ? ' current' : ''),
      style: `--seat:${m.color}`, title: m.id === p.current_member_id ? 'いま歌っている人' : 'この人にマイクを渡す',
      onclick: () => setSinger(m.id),
    }, el('i', { class: 'dot' }), avatarEl(m), el('span', { class: 'nm' }, m.name),
      queue.includes(m.id) ? el('span', { class: 'q' }, `次${queue.indexOf(m.id) + 1}`) : null,
      m.best != null ? el('span', { class: 'b' }, fmtScore(m.best)) : null))),
    el('button', { class: 'ghost small', onclick: showQr }, 'QR・あいことば'),
    el('button', {
      class: 'ghost small', onclick: async () => { if (confirm('パーティーを終了しますか？')) await endParty(); },
    }, 'パーティー終了'),
  );
}

function showQr() {
  const p = partyLive();
  if (!p) return;
  let d = $('partyqr');
  if (!d) { d = el('dialog', { id: 'partyqr', class: 'qrdlg' }); document.body.append(d); }
  d.replaceChildren(
    el('div', { class: 'qr' }, el('img', { src: `/api/party/${p.code}/qr.svg`, alt: 'QR' })),
    el('div', { class: 'pcode big' }, p.code),
    el('div', { class: 'dim' }, p.join_url.replace(/^https?:\/\//, '')),
    el('p', { class: 'dim', style: 'max-width:320px;line-height:1.6;font-size:13px' },
      'スマホでQRを読むか、このURLを開いて参加。ニックネームだけでも、アカウントでも参加できます。'),
    el('button', { class: 'primary', onclick: () => d.close() }, 'とじる'),
  );
  d.showModal();
}
