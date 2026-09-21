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

  // HIDDEN BY DEFAULT, REVEALED BY THE POINTER.
  //
  // The previous behaviour was scroll-coupled: hide on scroll down, reveal on scroll up. It
  // never hid in the arr apps, and the reason is written in its own comment. It listened in the
  // CAPTURE phase specifically because "many of these apps scroll an inner element rather than
  // the window" — and then read `window.pageYOffset`, which stays 0 forever when an inner
  // element is the thing scrolling. The listener fired on every scroll and computed 0 every
  // time, so `y > 90` was never true and the bar never moved.
  //
  // Rather than only repair that, the resting state is now HIDDEN. A persistent bar spends the
  // whole session covering 38px of an app we did not write, to show navigation the user needs
  // for a few seconds at a time. Reveal-on-approach costs nothing when unused and is the
  // behaviour that was actually wanted.
  //
  // Scroll still reveals, because a user who scrolls up is usually heading for navigation — and
  // that path now reads the scroll position off whichever element scrolled.
  function autoHide(nav) {
    var HIDDEN = C + '--hidden';

    // Hysteresis, not a single threshold. One boundary makes the bar flicker when the pointer
    // sits near it: every sub-pixel jitter across the line toggles a 280ms transition. Reveal
    // at 48px, hide only past 90px, and the dead band between them absorbs the jitter.
    var REVEAL_AT = 48;
    var HIDE_PAST = 90;

    // The bar itself occupies the top 38px, so a pointer ON the bar is inside REVEAL_AT and it
    // stays open while in use. No separate mouseenter handling is needed for that.
    nav.classList.add(HIDDEN);

    document.addEventListener('mousemove', function (ev) {
      if (ev.clientY < REVEAL_AT) {
        nav.classList.remove(HIDDEN);
      } else if (ev.clientY > HIDE_PAST) {
        nav.classList.add(HIDDEN);
      }
    }, { passive: true });

    // Touch has no hover. A tap in the top strip toggles instead, so the bar is reachable on a
    // tablet without making it permanent for everyone else.
    document.addEventListener('touchstart', function (ev) {
      var t = ev.touches && ev.touches[0];
      if (t && t.clientY < REVEAL_AT) nav.classList.remove(HIDDEN);
    }, { passive: true });

    // Leaving the window entirely re-hides: otherwise the bar stays open behind whatever the
    // user switched to and is still open when they come back.
    document.addEventListener('mouseleave', function () {
      nav.classList.add(HIDDEN);
    }, { passive: true });

    var ticking = false;
    var pending = 0;

    function apply() {
      // Near the top of ANY scroller, reveal. This is the fix for the original bug: the
      // position comes from the element that scrolled, not from the window.
      if (pending <= 90) nav.classList.remove(HIDDEN);
      ticking = false;
    }

    function schedule(ev) {
      // Read synchronously — by the time the rAF callback runs, `ev` is gone.
      var t = ev && ev.target;
      if (t && t !== document && t !== window && typeof t.scrollTop === 'number') {
        pending = t.scrollTop;
      } else {
        pending = window.pageYOffset || document.documentElement.scrollTop || 0;
      }
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(apply);
      }
    }

    // Capture phase so scroll from any inner scroller is seen; scroll does not bubble.
    window.addEventListener('scroll', schedule, { passive: true, capture: true });
  }

  // No `cache: 'no-store'` here: it would defeat the Cache-Control the
  // catalyst-asset-cache middleware sets on this route and refetch the manifest
  // on every navigation. The sidecar refreshes it every 5 minutes and the cache
  // max-age matches, so staleness is bounded to one refresh cycle.
  //
  // The manifest is written by a sidecar into the same volume nginx serves, so
  // for a few seconds after a pod rolls the theme is already up while the
  // manifest is not. Without a retry, anyone loading in that window gets no nav
  // and no reason why. Three tries with backoff covers it; after that we stay
  // quiet, because the nav is cosmetic and must never surface an error into a
  // third-party app.
  function start(attempt) {
    attempt = attempt || 0;
    fetch(MANIFEST, { credentials: 'omit' })
      .then(function (r) {
        if (r.ok) return r.json();
        throw new Error('manifest ' + r.status);
      })
      .then(function (d) { if (d) build(d); })
      .catch(function () {
        if (attempt < 2) setTimeout(function () { start(attempt + 1); }, 1000 * (attempt + 1));
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
