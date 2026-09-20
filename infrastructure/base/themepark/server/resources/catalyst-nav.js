/* ============================================================================
 * CATALYST — cross-app nav bar
 * ----------------------------------------------------------------------------
 * Injected into every themed app by the `catalyst-nav` Traefik middleware.
 * Styling lives in the theme (src/60-nav.css), already loaded on these pages.
 *
 * NOTHING ABOUT ANY APP IS HARDCODED HERE. The link list is fetched from
 * catalyst-nav.json, which a sidecar regenerates from the gethomepage.dev/*
 * annotations on the cluster's IngressRoutes. Theme a new app and it appears
 * here on the next refresh; delete one and it disappears.
 *
 * Defensive by design — this runs inside nine third-party applications:
 *   - every failure is silent, because a broken nav must never break the app
 *   - one namespaced class prefix, no globals beyond a single guard flag
 *   - re-entrant: SPAs re-run scripts, so it refuses to build twice
 * ========================================================================== */
(function () {
  'use strict';

  if (window.__catalystNav) return;           // SPA re-execution guard
  window.__catalystNav = true;

  var MANIFEST = '/catalyst/resources/catalyst-nav.json';
  var C = 'catalyst-nav';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // Current app = the host we are on. Derived, never configured.
  function isCurrent(href) {
    try {
      return new URL(href, location.href).hostname === location.hostname;
    } catch (e) {
      return false;
    }
  }

  function linkFor(item) {
    var a = el('a', C + '__link', item.name);
    a.href = item.href;
    if (isCurrent(item.href)) {
      a.className += ' ' + C + '__link--current';
      a.setAttribute('aria-current', 'page');
    }
    // Dim destinations that do not carry the theme, so it is obvious you are
    // about to land somewhere that looks different.
    if (item.themed === false) a.className += ' ' + C + '__link--unthemed';
    return a;
  }

  function buildGroup(group) {
    var wrap = el('div', C + '__group');
    var label = el('div', C + '__label');
    label.appendChild(document.createTextNode(group.name));
    label.appendChild(el('span', C + '__caret', '▾'));
    label.tabIndex = 0;
    label.setAttribute('role', 'button');
    label.setAttribute('aria-haspopup', 'true');
    label.setAttribute('aria-expanded', 'false');

    var menu = el('ul', C + '__menu');
    var active = false;
    group.items.forEach(function (item) {
      if (isCurrent(item.href)) active = true;
      var li = el('li');
      li.appendChild(linkFor(item));
      menu.appendChild(li);
    });
    if (active) wrap.className += ' ' + C + '__group--active';

    // Hover opens it via CSS alone. This adds keyboard and touch, which hover
    // cannot serve.
    function toggle(open) {
      wrap.classList.toggle('is-open', open);
      label.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    label.addEventListener('click', function () {
      toggle(!wrap.classList.contains('is-open'));
    });
    label.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        toggle(!wrap.classList.contains('is-open'));
      } else if (ev.key === 'Escape') {
        toggle(false);
      }
    });
    wrap.addEventListener('focusout', function () {
      // Defer so focus has landed before we test containment.
      setTimeout(function () {
        if (!wrap.contains(document.activeElement)) toggle(false);
      }, 0);
    });

    wrap.appendChild(label);
    wrap.appendChild(menu);
    return wrap;
  }

  function build(data) {
    var groups = (data && data.groups) || [];
    if (!groups.length) return;

    var nav = el('nav', C);
    nav.setAttribute('aria-label', 'Catalyst applications');
    nav.appendChild(el('div', C + '__brand', 'CATALYST'));

    // Adaptive: one group reads better as a flat row than as a lone dropdown.
    // Derived from the data, so it changes on its own as the cluster grows.
    if (groups.length === 1) {
      groups[0].items.forEach(function (item) {
        var a = linkFor(item);
        a.className += ' ' + C + '__link--flat';
        nav.appendChild(a);
      });
    } else {
      groups.forEach(function (g) { nav.appendChild(buildGroup(g)); });
    }

    nav.appendChild(el('div', C + '__spacer'));
    nav.appendChild(el('div', C + '__here', location.hostname));

    document.body.appendChild(nav);
    autoHide(nav);
  }

  // Auto-hide on scroll down, reveal on scroll up. rAF-throttled so it cannot
  // become a scroll-performance problem inside a host app.
  function autoHide(nav) {
    var last = 0;
    var ticking = false;

    function onScroll() {
      var y = window.pageYOffset || document.documentElement.scrollTop || 0;
      // Never hide near the top, and ignore sub-pixel jitter.
      if (y > 90 && y - last > 4) {
        nav.classList.add(C + '--hidden');
      } else if (last - y > 4 || y <= 90) {
        nav.classList.remove(C + '--hidden');
      }
      last = y;
      ticking = false;
    }

    // Many of these apps scroll an inner element rather than the window, so
    // listen in the CAPTURE phase to catch scroll from any scroller.
    function schedule() {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(onScroll);
      }
    }
    window.addEventListener('scroll', schedule, { passive: true, capture: true });

    // Pointer near the top always reveals it — otherwise a hidden bar in a
    // non-window scroller could be hard to get back.
    document.addEventListener('mousemove', function (ev) {
      if (ev.clientY < 48) nav.classList.remove(C + '--hidden');
    }, { passive: true });
  }

  function start() {
    fetch(MANIFEST, { credentials: 'omit' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) build(d); })
      .catch(function () { /* nav is cosmetic; never surface an error */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
