/* ============================================================================
 *  ____      _        _           _
 * / ___|__ _| |_ __ _| |_   _ ___| |_
 * | |   / _` | __/ _` | | | | / __| __|
 * | |__| (_| | || (_| | | |_| \__ \ |_
 * \____\__,_|\__\__,_|_|\__, |___/\__|
 *                       |___/
 *  a theme.park theme for the Catalyst homelab
 *
 * GENERATED — do not edit. Source: workspace/catalyst-themepark/src/60-nav.js
 * Rebuild:   ./build.sh            Publish: ./build.sh --publish
 *
 * Palette is catalyst-ui's `catalyst` dark theme (the design system of record).
 * Fonts are inlined as data: URIs so the whole theme is a single request with
 * no cross-origin font fetch. See src/10-fonts.css.tmpl for why.
 * ========================================================================== */

/* ============================================================================
 * CATALYST — cross-app nav bar
 * ----------------------------------------------------------------------------
 * THE single source for the nav script. Paired with src/60-nav.css by layer
 * number; build.sh emits dist/catalyst-nav.js and publishes it into the
 * homelab repo. There were once THREE hand-maintained copies of this file and
 * all three had drifted — the deployed one was a whole rewrite ahead of the one
 * labelled "source". Do not reintroduce a copy: edit this file, run
 * `./build.sh --publish`, and let `./build.sh --check` fail the build if a copy
 * ever diverges again.
 *
 * NOTHING ABOUT ANY APP IS HARDCODED HERE. The link list AND the per-app
 * behaviour both come from catalyst-nav.json, which a sidecar regenerates from
 * annotations on the cluster's IngressRoutes. Theme a new app and it appears on
 * the next refresh; tune one app's bar by annotating that app's own route.
 *
 * Defensive by design — this runs inside fourteen third-party applications:
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

  /* -- Configuration --------------------------------------------------------
   * Resolved per app, lowest precedence first:
   *
   *   DEFAULTS  <-  manifest.defaults  <-  manifest.hosts[location.hostname]
   *
   * Nothing here names an app. The sidecar fills `defaults` and `hosts` from
   * `catalyst.nav/*` annotations, so an app's bar is tuned in the same file
   * that already declares its homepage entry — one place, next to the app.
   *
   *   mode          'overlay' floats above the app, revealed by the pointer.
   *                 'push'    reserves a strip so the app is never covered.
   *                 'off'     no bar on this app at all.
   *   revealAt      overlay: pointer must come within this many px of the top.
   *   hidePast      overlay: pointer past this many px re-hides.
   *   height        bar height; also drives the CSS via --catalyst-nav-h.
   *   scrollReveal  overlay: also reveal near the top of any scroller.
   *
   * WHY revealAt defaults to 6 rather than something roomier: the app's own top
   * nav lives in roughly the first 40px. A generous trigger meant that reaching
   * for the app's menu summoned this bar on top of it at z-index 9998 and ate
   * the click. The trigger has to be tighter than the thing it must not fight,
   * so it is a deliberate jab at the very edge. hidePast sits just past the bar
   * itself for the same reason — a wide dead band leaves the bar open exactly
   * where the app's chrome is.
   *
   * scrollReveal is OFF by default for that same reason: scrolling a list back
   * to the top is precisely when you then reach for the app's header, so
   * revealing there recreated the problem through a second door.
   * ------------------------------------------------------------------------ */
  var DEFAULTS = {
    mode: 'overlay',
    revealAt: 6,
    hidePast: 48,
    height: 38,
    scrollReveal: false
  };

  // Touch has no hover, so a 6px target is unusable. Deliberately NOT part of
  // the config surface: it is a property of fingers, not of any one app.
  var TOUCH_REVEAL_AT = 14;

  // Copies only keys DEFAULTS declares, so a malformed or hostile manifest
  // cannot inject arbitrary properties into the config object.
  function assign(target, src) {
    if (!src) return target;
    for (var k in DEFAULTS) {
      if (Object.prototype.hasOwnProperty.call(src, k)) target[k] = src[k];
    }
    return target;
  }

  function resolveConfig(data) {
    var cfg = assign({}, DEFAULTS);
    assign(cfg, data.defaults);
    assign(cfg, (data.hosts || {})[location.hostname]);
    return cfg;
  }

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
    var cfg = resolveConfig(data);
    if (cfg.mode === 'off') return;

    var groups = (data && data.groups) || [];
    if (!groups.length) return;

    // One number, one place. The stylesheet reads --catalyst-nav-h for every
    // height, offset and the push-mode reservation, so changing the bar's
    // height never means hunting hardcoded 38s through a stylesheet.
    document.documentElement.style.setProperty(
      '--catalyst-nav-h', cfg.height + 'px');

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

    if (cfg.mode === 'push') {
      // Reserve the strip instead of floating over the app. The class goes on
      // <html> from JS rather than living as a bare rule in the stylesheet, so
      // the sheet stays inert on any page where the script did not build — a
      // failed manifest fetch must never leave an app padded down with no bar
      // in the gap.
      document.documentElement.classList.add(C + '-push');
      return;
    }

    autoHide(nav, cfg);
  }

  /* -- Overlay mode: hidden at rest, revealed by the pointer ----------------
   * The resting state is HIDDEN. A persistent overlay bar would spend the whole
   * session covering the top of an app we did not write, to show navigation
   * needed for a few seconds at a time. Apps that would rather surrender the
   * space permanently should use mode:'push' — then nothing is ever covered and
   * none of this runs.
   * ------------------------------------------------------------------------ */
  function autoHide(nav, cfg) {
    var HIDDEN = C + '--hidden';

    // Hysteresis, not a single threshold: one boundary makes the bar flicker
    // when the pointer sits near it, because every sub-pixel jitter across the
    // line toggles a 280ms transition. The gap between revealAt and hidePast
    // absorbs that.
    nav.classList.add(HIDDEN);

    document.addEventListener('mousemove', function (ev) {
      // Never hide while the pointer is inside the bar or an open dropdown.
      // Menus are several times taller than the bar, so a pure clientY test
      // slid the whole thing away mid-hover the moment you reached for the
      // third item in a list.
      if (nav.contains(ev.target) || ev.clientY < cfg.revealAt) {
        nav.classList.remove(HIDDEN);
      } else if (ev.clientY > cfg.hidePast) {
        nav.classList.add(HIDDEN);
      }
    }, { passive: true });

    // Touch has no hover. A tap in the top strip reveals, so the bar is
    // reachable on a tablet without making it permanent for everyone else.
    document.addEventListener('touchstart', function (ev) {
      var t = ev.touches && ev.touches[0];
      if (t && t.clientY < TOUCH_REVEAL_AT) nav.classList.remove(HIDDEN);
    }, { passive: true });

    // Leaving the window entirely re-hides: otherwise the bar stays open behind
    // whatever the user switched to and is still open when they come back.
    document.addEventListener('mouseleave', function () {
      nav.classList.add(HIDDEN);
    }, { passive: true });

    if (!cfg.scrollReveal) return;

    // Opt-in only. Reads the scroll position off whichever element scrolled,
    // because many of these apps scroll an inner element and window.pageYOffset
    // stays 0 forever in that case — the bug that made an earlier
    // scroll-coupled version never fire at all.
    var ticking = false;
    var pending = 0;

    function apply() {
      if (pending <= cfg.hidePast) nav.classList.remove(HIDDEN);
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

    // Capture phase so scroll from any inner scroller is seen; scroll does not
    // bubble.
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
