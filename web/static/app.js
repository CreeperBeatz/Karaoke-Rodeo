// The app shell's router (see app.html). One document; each view is a module with
//   title           - tab title after the brand
//   auth            - true: someone must be signed in; 'admin': and be an admin
//   load(ctx)       - fetch everything the view needs (runs while the previous view is still on screen)
//   render(main, data, ctx) - build the view into <main>; may return a cleanup function (intervals, listeners)
// A move between views: import + load first, then swap <main> inside a view transition, so the wipe in common.css
// always reveals a finished page. Anything that is not a view (うたう画面, ログイン, パーティー参加, ラベラー) is
// left to the browser as an ordinary navigation.
import { ApiError, getMe, renderNav, setNavActive, isGuest, el } from '/static/common.js';

const BRAND = 'カラオケ.ロデオ';
// path → [view module, header link that lights up]. Imports are literal so the build stamp reaches them.
const ROUTES = {
  '/': [() => import('/static/view-songs.js'), '/'],
  '/songs': [() => import('/static/view-songs.js'), '/'],
  '/stats': [() => import('/static/view-stats.js'), '/stats'],
  '/leaderboard': [() => import('/static/view-leaderboard.js'), '/leaderboard'],
  '/profile': [() => import('/static/view-profile.js'), '/profile'],
  '/about': [() => import('/static/view-about.js'), '/about'],
  '/admin': [() => import('/static/view-admin.js'), '/admin'],
};
const viewName = (path) => path === '/' ? 'songs' : path.slice(1);

const main = document.getElementById('page');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let cleanup = null;   // the current view's teardown
let seq = 0;          // a navigation that is overtaken by a newer one gives up quietly

const loginUrl = (u) => '/login?next=' + encodeURIComponent(u.pathname + u.search + u.hash);

/** Go to an app URL client-side; anything the router does not own becomes a normal page load. */
export function navigate(href, opts = {}) { return go(new URL(href, location.href), opts); }

async function go(u, { replace = false, pop = false, first = false } = {}) {
  const route = ROUTES[u.pathname];
  if (!route) { location.href = u.href; return; }
  const [load, nav] = route;
  const my = ++seq;
  document.documentElement.classList.add('busy');
  try {
    const [{ default: view }, me] = await Promise.all([load(), getMe().catch(() => null)]);
    if (my !== seq) return;
    setNavActive(nav);                                   // the header answers the click at once
    if (view.auth && !me) { location.replace(loginUrl(u)); return; }
    const ctx = { me, guest: !me && isGuest(), url: u, params: u.searchParams, navigate };
    let data = null, err = null;
    if (view.auth === 'admin' && !me.is_admin) err = new Error('管理者のみ / admin only');
    else if (view.load) { try { data = await view.load(ctx); } catch (e) { err = e; } }
    if (my !== seq) return;
    if (err instanceof ApiError && err.status === 401) { location.replace(loginUrl(u)); return; }
    if (!pop && !first) {
      history.replaceState({ scroll: scrollY }, '');     // remember where this page was, for 戻る
      history[replace ? 'replaceState' : 'pushState']({ scroll: 0 }, '', u.pathname + u.search + u.hash);
    }
    const swap = () => {
      try { cleanup?.(); } catch (e) { console.error(e); }
      cleanup = null;
      main.replaceChildren();
      main.className = `page v-${viewName(u.pathname)}`;
      document.title = view.title ? `${BRAND} - ${view.title}` : BRAND;
      if (err) main.append(el('div', { class: 'msg err' }, err.message || String(err)));
      else cleanup = view.render(main, data, ctx) || null;
      scrollTo(0, pop ? (history.state && history.state.scroll) || 0 : 0);
    };
    // The first view has nothing to wipe over; reduced motion asks for a plain swap.
    if (!first && document.startViewTransition && !reduced.matches) await document.startViewTransition(swap).updateCallbackDone;
    else swap();
  } catch (e) {
    console.error(e);
    if (my === seq) { main.replaceChildren(el('div', { class: 'msg err' }, e.message || String(e))); }
  } finally {
    if (my === seq) document.documentElement.classList.remove('busy');
  }
}

// Same-origin links into a view are taken over; everything else (new tab, modifier keys, downloads,
// other documents) is left to the browser.
document.addEventListener('click', (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = e.target.closest('a[href]');
  if (!a || a.target || a.hasAttribute('download')) return;
  const u = new URL(a.href, location.href);
  if (u.origin !== location.origin || !ROUTES[u.pathname]) return;
  e.preventDefault();
  if (u.pathname === location.pathname && u.search === location.search) { scrollTo({ top: 0, behavior: 'smooth' }); return; }
  go(u);
});
addEventListener('popstate', () => go(new URL(location.href), { pop: true }));
history.scrollRestoration = 'manual';

// ---- boot ----
const start = new URL(location.href);
renderNav((ROUTES[start.pathname] || [null, ''])[1]);
go(start, { first: true });
