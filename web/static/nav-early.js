// Runs where it stands - right under <header class="top">, before the browser has shown anything (the <link
// rel="expect"> in <head> holds the first frame back until <main> is parsed). It puts back the header this tab
// last saw: common.js keeps the finished header's markup in sessionStorage (see cacheNav), so a move between pages
// starts from a full bar instead of an empty strip that fills in later, and the view transition, which snapshots
// the new page's first frame, carries a real header across. Nothing here is live: common.js redraws the same
// header with its menus wired as soon as it loads; for the few tens of ms in between the burger and menus are inert.
(function () {
  try {
    var h = document.querySelector('header.top');
    var html = sessionStorage.getItem('karaoke_nav');
    if (!h || h.firstChild || !html) return;
    h.innerHTML = html;
    // The active link is this page's path - except /play and /songs, which belong to うたう (renderNav('/') there).
    var p = location.pathname, q = p.indexOf('/play') === 0 || p === '/songs' ? '/' : p;
    var a = h.querySelectorAll('nav.main a');
    for (var i = 0; i < a.length; i++) a[i].classList.toggle('active', a[i].getAttribute('href') === q);
    // A menu that was open when the last page was left must not come back open.
    var o = h.querySelectorAll('.open');
    for (i = 0; i < o.length; i++) o[i].classList.remove('open');
    var x = h.querySelectorAll('[aria-expanded]');
    for (i = 0; i < x.length; i++) x[i].setAttribute('aria-expanded', 'false');
  } catch (e) {}
})();
