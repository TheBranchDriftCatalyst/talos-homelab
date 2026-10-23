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
 *   - one namespaced class prefix, and ONE global: window.__catalystNav,
 *     which is both the re-entry guard and the applets' registration surface
 *   - re-entrant: SPAs re-run scripts, so it refuses to build twice
 * ========================================================================== */
(function () {
  'use strict';

  /* -- The one global -------------------------------------------------------
   * This was a bare `true`. It is an object now so that applets have somewhere
   * to register, and the SPA guard below is unchanged by the promotion: it only
   * ever tested truthiness, and an object is truthy.
   *
   * THIS SHAPE IS A CROSS-REPO API. An applet is built, versioned and deployed
   * from its own repo and only meets this file at runtime, so the keys below
   * are a contract rather than an internal:
   *
   *   version   integer. Bumped on any breaking change to this object.
   *   slot      the dock element, or null until the bar is in the document.
   *             Published here precisely so a LATE applet can see that it has
   *             somewhere to render immediately.
   *   applets   name -> { name, render, dock, failed }. Introspection; also
   *             the pending queue (see the applet section below).
   *   register(name, render) -> boolean
   *             name    unique non-empty string. A second registration under a
   *                     name already taken is refused; the first one wins.
   *             render  function (dock, nav). Called at most ONCE, with its own
   *                     empty <div> already appended to the bar. Append into
   *                     that; do not touch anything outside it.
   *             returns true if the registration was ACCEPTED -- not that
   *                     render has run, because it may still be waiting for
   *                     the bar -- and false if it was refused or threw.
   *             Safe before OR after the bar is built. Both orders happen.
   * ---------------------------------------------------------------------- */
  if (window.__catalystNav) return;           // SPA re-execution guard
  var NAV = window.__catalystNav = {
    version: 1,
    slot: null,
    applets: {},
    register: register                        // hoisted; defined below
  };

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
    scrollReveal: false,
    // intensity  amplitude of every animation in layer 45. 1 is full, 0 is
    //            flat, above 1 is obnoxious and legal. Turn this down for an
    //            app whose own UI is already busy.
    // fx         false removes the injected atmosphere layers outright and
    //            stops all animation. Distinct from intensity 0, which keeps
    //            the horizon and bloom rendering as static texture.
    intensity: 1,
    fx: true,
    // applets    bundles to dock into the bar, as an array of paths or of
    //            { src: path }. Allowlisted to same-origin paths under
    //            /catalyst/ -- see APPLET_URL_RULES, and the asset route's own
    //            writeup for why that prefix is the only trustworthy one.
    //
    //            Declared HERE and not only in the manifest because assign()
    //            copies only the keys this object names: an undeclared
    //            `applets` would be silently stripped out of every manifest.
    //            Being part of the config surface also means it resolves
    //            through the usual precedence, so one host can carry an applet
    //            the rest of the cluster does not, for free.
    applets: []
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

  /* -- The atmosphere layers ------------------------------------------------
   * Layer 45 of the stylesheet draws a receding horizon, a bloom and a glitch
   * slice. Each needs a real element: a pseudo-element cannot hold a child, and
   * both the horizon and the glitch need one transform nested inside another
   * (perspective on the parent, scroll on the child). html::before and
   * html::after are already spoken for by layer 30, and body::before/::after by
   * theme.park's own base sheets — so these three are injected here.
   *
   * DELIBERATELY NOT GATED ON THE NAV. This runs before the manifest is
   * fetched and regardless of whether a bar is ever built: an app configured
   * mode:'off', or one whose manifest request fails, still has the stylesheet
   * and should still look like the theme. Config, when it arrives, is applied
   * on top by applyFx().
   * ---------------------------------------------------------------------- */
  var FX = 'catalyst-fx';

  function installFx() {
    if (document.getElementById(FX)) return;         // SPA / double-call guard
    if (!document.body) return;

    var host = el('div', FX);
    host.id = FX;
    // Presentational in full. Screen readers must never announce it, and it
    // must never take a tab stop or eat a click.
    host.setAttribute('aria-hidden', 'true');
    ['horizon', 'bloom', 'glitch'].forEach(function (part) {
      host.appendChild(el('div', FX + '__' + part));
    });
    // FIRST child, not appended: these are backdrops, and the stylesheet keeps
    // them out of the way by z-index rather than by document order — but a
    // trailing element is one `position: static` regression away from sitting
    // on top of the app.
    document.body.insertBefore(host, document.body.firstChild);

    // The boot cascade is gated on this class and the class is REMOVED once the
    // sequence has played. Both halves matter. servarr is an SPA that swaps its
    // content on every sidebar click, so a CRT power-on tied to element
    // creation would re-fire forever; and while the class is present, a row's
    // entry animation is re-declared every time :hover stops applying, so
    // brushing the pointer across a table would deal each row back in. Removing
    // it leaves no animation for hover to fall back to.
    document.documentElement.classList.add('catalyst-boot');
    setTimeout(function () {
      document.documentElement.classList.remove('catalyst-boot');
    }, 1600);
  }

  /* Applied once the manifest resolves. Split from installFx so the layers are
   * never waiting on the network to appear. */
  function applyFx(cfg) {
    var root = document.documentElement;
    // Number() rather than parseFloat: annotations arrive as strings, and
    // parseFloat('0.5abc') is 0.5 while Number('0.5abc') is NaN. A malformed
    // value should fall back to the default, not silently half-apply.
    var n = Number(cfg.intensity);
    if (!isFinite(n) || n < 0) n = DEFAULTS.intensity;
    root.style.setProperty('--cat-anim', String(n));

    // The attribute, not a class: it is a three-state switch in the stylesheet
    // and reads clearly in devtools next to the other data-* the apps set.
    if (cfg.fx === false || cfg.fx === 'false') {
      root.setAttribute('data-catalyst-anim', 'off');
      root.classList.remove('catalyst-boot');
    } else {
      root.removeAttribute('data-catalyst-anim');
    }
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

  /* Hover opens a dropdown via CSS alone. This adds keyboard and touch, which
   * hover cannot serve. Shared by the app groups and the settings gear so the
   * two can never drift apart in focus or aria behaviour. */
  function wireDropdown(wrap, label) {
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
  }

  /* -- Applets: the dock, the registry, the loader --------------------------
   * An applet cannot inject itself. A second `rewriteBody` middleware stacked
   * onto a route that already has one silently never fires, so there is exactly
   * one injected script on these apps and this is it. An applet therefore rides
   * in here: the bar renders a slot, this file loads the bundles the manifest
   * names, and each bundle calls register() to get an element of its own.
   *
   * TWO ORDERS, BOTH REAL, AND THE ORDER IS NOT OURS TO CHOOSE. build() is only
   * reached through start() -> fetch(MANIFEST) -> .then(build), with three tries
   * and 1s/2s backoff; a bundle is a <script defer> the browser schedules on its
   * own. Either can win:
   *
   *   register() BEFORE build()   NAV.slot is null, so the entry simply sits in
   *                               NAV.applets with dock null, and build()
   *                               flushes it once the slot exists.
   *   register() AFTER  build()   NAV.slot is already published, so renderApplet
   *                               runs on the spot.
   *
   * There is no second data structure for the first case. An entry whose dock is
   * null IS the queue, and both paths go through the same renderApplet call --
   * which is what stops the early path and the late path from drifting, the way
   * three hand-maintained copies of this file once did.
   *
   * EVERYTHING HERE IS SILENT. Not quietly, deliberately: the manifest is parsed
   * and these bundles are run inside forty applications we did not write, and
   * the existing fetch gives up without a word after three tries for exactly
   * that reason. A refused URL, a 404, a bundle that throws on load and a render
   * callback that throws all leave the bar fully working and say nothing.
   * ------------------------------------------------------------------------ */

  // Same-origin, under the asset prefix -- which is the only route gated by
  // both HostRegexp and lan-only, and so the only place an applet may come
  // from. Anywhere else is either another origin or ungated.
  var APPLET_PREFIX = '/catalyst/';

  /* Every reason to refuse an applet URL, declared once and walked by a generic
   * loop, in the same spirit as SETTINGS below: adding a rule needs no new
   * control flow. `why` is documentation and test-fixture naming only -- it is
   * never logged, never thrown and never shown.
   *
   * It is an ALLOWLIST with deny rules in front of it. The last two rules alone
   * would be sufficient, being an anchored whole-string match on a conservative
   * charset under a fixed prefix. The deny rules above them name the specific
   * attack each one closes, so a reader does not have to derive them from a
   * regex, and so widening that charset later cannot silently reopen one. */
  var APPLET_URL_RULES = [
    { why: 'not a non-empty string',
      bad: function (s) { return typeof s !== 'string' || !s; } },

    // '//evil.example/x.js' takes the page's scheme and somebody else's host,
    // and looks like a path at a glance.
    { why: 'protocol-relative',
      bad: function (s) { return s.slice(0, 2) === '//'; } },

    // Any scheme at all: https:, data:, javascript:. A colon before the first
    // slash is a scheme by RFC 3986, which covers every one of them including
    // schemes that do not exist yet.
    { why: 'absolute or schemed',
      bad: function (s) { return /^[a-zA-Z][a-zA-Z0-9+.\-]*:/.test(s); } },

    // '/\\evil.example/x.js'. The URL parser folds a backslash to a slash, so
    // this is a protocol-relative URL that no substring test for '//' sees.
    { why: 'contains a backslash',
      bad: function (s) { return s.indexOf('\\') !== -1; } },

    // Traversal. The prefix test below does not stop '/catalyst/../../x.js',
    // which leaves the gated route while still starting inside it.
    { why: 'contains ..',
      bad: function (s) { return s.indexOf('..') !== -1; } },

    // Percent-encoding hides the two rules above from a substring test:
    // '%2e%2e' and '%5c' are '..' and '\\' by the time the browser fetches.
    { why: 'percent-encoded',
      bad: function (s) { return s.indexOf('%') !== -1; } },

    { why: 'outside ' + APPLET_PREFIX,
      bad: function (s) {
        return s.slice(0, APPLET_PREFIX.length) !== APPLET_PREFIX;
      } },

    // The allowlist proper, anchored at both ends: a plain path built only from
    // characters a path needs, ending .js. No query, no fragment, no host, no
    // whitespace, no quotes, nothing that could carry a second meaning. Version
    // an applet in its path, not in a query string.
    { why: 'not a plain .js path',
      bad: function (s) { return !/^[A-Za-z0-9._~\/-]+\.js$/.test(s); } }
  ];

  // Returns the `why` of the first rule that refuses `src`, or null if every
  // rule passed. Null means allowed -- the inverse is deliberate, so the
  // interesting case has a name and the dull one does not.
  function appletUrlRefusal(src) {
    for (var i = 0; i < APPLET_URL_RULES.length; i++) {
      if (APPLET_URL_RULES[i].bad(src)) return APPLET_URL_RULES[i].why;
    }
    return null;
  }

  /* Render one registration into the slot. The guard does all three jobs: no
   * slot yet means stay queued, an existing dock means already rendered, and
   * `failed` means do not try a second time. */
  function renderApplet(entry) {
    if (!NAV.slot || entry.dock || entry.failed) return;

    var dock = el('div', C + '__applet');
    dock.setAttribute('data-catalyst-applet', entry.name);
    // Appended BEFORE render runs, so the applet can measure and position
    // against a dock that is already laid out in the bar.
    NAV.slot.appendChild(dock);
    entry.dock = dock;

    try {
      entry.render(dock, NAV);
    } catch (e) {
      // Leave no half-built stub in the bar, and never retry: a render that
      // throws once throws again, and retrying would spend the session growing
      // empty divs in somebody else's header.
      entry.failed = true;
      entry.dock = null;
      if (dock.parentNode) dock.parentNode.removeChild(dock);
    }
  }

  function register(name, render) {
    try {
      if (typeof name !== 'string' || !name) return false;
      if (typeof render !== 'function') return false;
      // A plain `in`-style truth test rather than hasOwnProperty, so that
      // inherited names ('__proto__', 'constructor', 'hasOwnProperty') are
      // refused rather than written. Refusing them is the safe failure.
      if (NAV.applets[name]) return false;
      NAV.applets[name] = {
        name: name, render: render, dock: null, failed: false
      };
      // A no-op while slot is null, and that no-op IS the queue.
      renderApplet(NAV.applets[name]);
      return true;
    } catch (e) {
      return false;
    }
  }

  // Called once, by build(), immediately after the slot is published.
  function flushApplets() {
    for (var name in NAV.applets) {
      if (Object.prototype.hasOwnProperty.call(NAV.applets, name)) {
        renderApplet(NAV.applets[name]);
      }
    }
  }

  // Sources already injected, so two `hosts` entries naming the same bundle --
  // or any future second call to the loader -- cannot load one twice.
  var APPLETS_LOADED = {};

  function loadApplet(spec) {
    try {
      var src = (spec && typeof spec === 'object') ? spec.src : spec;
      if (appletUrlRefusal(src)) return;       // silently, always
      if (APPLETS_LOADED[src]) return;
      APPLETS_LOADED[src] = true;

      var s = document.createElement('script');
      // defer rather than async: two applets should run in the order the
      // manifest lists them, and neither should block the host app's parse.
      s.defer = true;
      s.setAttribute('data-catalyst-applet', 'true');
      // Consume the element's error event and take the tag back out. This does
      // NOT suppress the browser's own network log for a 404 -- nothing in
      // script can -- but it does mean a missing bundle leaves no handler-less
      // error event and no dead tag behind in the host's <head>.
      s.onerror = function () {
        if (s.parentNode) s.parentNode.removeChild(s);
      };
      s.src = src;
      (document.head || document.documentElement).appendChild(s);
    } catch (e) {
      // Nothing to report to, and nowhere to report it. See the file header.
    }
  }

  // Array-ish, not Array.isArray: this value came out of somebody's JSON and
  // the whole point of the surrounding block is that it may be anything.
  function loadApplets(list) {
    if (!list || typeof list.length !== 'number') return;
    for (var i = 0; i < list.length; i++) loadApplet(list[i]);
  }

  /* -- User preferences -----------------------------------------------------
   * PER ORIGIN, and that is a constraint rather than a choice: every app is its
   * own hostname, so one localStorage is not shared between them, and a cookie
   * scoped to `.talos00` would be rejected outright -- a single-label domain is
   * treated as a public suffix. So a preference set on one app is remembered
   * for THAT app, and turning it on everywhere means turning it on per app.
   *
   * Every read and write is wrapped. localStorage THROWS on access in some
   * privacy modes, and this bar is cosmetic: it must never surface an error
   * into an app we did not write.
   * ------------------------------------------------------------------------ */
  var PREF_KEY = 'catalyst-nav:prefs';

  function readPrefs() {
    try {
      return JSON.parse(window.localStorage.getItem(PREF_KEY)) || {};
    } catch (e) {
      return {};
    }
  }

  function writePrefs(prefs) {
    try {
      window.localStorage.setItem(PREF_KEY, JSON.stringify(prefs));
    } catch (e) {
      // Storage disabled or full. The toggle still applies for this page view;
      // it just will not be remembered. Silent on purpose.
    }
  }

  /* "Always visible" stops the auto-hide and leaves the bar resting on screen.
   *
   * It deliberately does NOT switch to mode:'push'. Push reserves the strip by
   * padding <html>, which only works for a document in normal flow -- layer 50
   * of the stylesheet says so outright, and almost every app here is an SPA
   * with a position:fixed header that padding cannot move. Pinning via push
   * would therefore slide the bar under the app's own header on exactly the
   * apps people use most, and fail differently in each one. Floating over the
   * top strip is the honest reading of "always visible" and behaves the same
   * everywhere. */
  function applyPinned(nav, on) {
    nav.classList.toggle(C + '--pinned', !!on);
    nav.classList.toggle(C + '--hidden', !on);
  }

  /* The settings menu's contents. Add an entry here and it renders itself --
   * label, hint, checkbox, persistence and the live apply all come from this
   * one object, so the next switch needs no new DOM code. */
  var SETTINGS = [
    {
      key: 'pinned',
      label: 'Always visible',
      hint: 'Keep the bar on screen instead of revealing it on hover.',
      apply: applyPinned
    }
  ];

  function buildSettings(nav, cfg, prefs) {
    var wrap = el('div', C + '__group ' + C + '__group--settings');
    var label = el('div', C + '__label');
    label.appendChild(el('span', C + '__gear', '\u2699'));
    label.tabIndex = 0;
    label.setAttribute('role', 'button');
    label.setAttribute('aria-haspopup', 'true');
    label.setAttribute('aria-expanded', 'false');
    label.setAttribute('aria-label', 'Nav bar settings');
    label.title = 'Nav bar settings';

    // Right-anchored: the gear sits at the right edge, so a left-anchored
    // panel would hang off the viewport.
    var menu = el('ul', C + '__menu ' + C + '__menu--right');

    SETTINGS.forEach(function (setting) {
      var row = el('label', C + '__setting');
      var box = document.createElement('input');
      box.type = 'checkbox';
      box.className = C + '__checkbox';
      box.checked = !!prefs[setting.key];

      var text = el('span', C + '__setting-text');
      text.appendChild(el('span', C + '__setting-label', setting.label));
      var hint = setting.hint;

      // An app configured mode:'push' already reserves the strip, so the bar is
      // permanently visible there no matter what this says. Show that as a
      // checked, disabled switch rather than an unchecked one that appears to
      // do nothing when clicked.
      if (setting.key === 'pinned' && cfg.mode === 'push') {
        box.checked = true;
        box.disabled = true;
        hint = 'This app is configured mode:push, so the bar is always visible here.';
      }

      if (hint) text.appendChild(el('span', C + '__setting-hint', hint));

      box.addEventListener('change', function () {
        prefs[setting.key] = box.checked;
        writePrefs(prefs);
        setting.apply(nav, box.checked);
      });

      row.appendChild(box);
      row.appendChild(text);
      var li = el('li');
      li.appendChild(row);
      menu.appendChild(li);
    });

    wireDropdown(wrap, label);
    wrap.appendChild(label);
    wrap.appendChild(menu);
    return wrap;
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

    wireDropdown(wrap, label);

    wrap.appendChild(label);
    wrap.appendChild(menu);
    return wrap;
  }

  function build(data) {
    var cfg = resolveConfig(data);

    // BEFORE the early returns below. The atmosphere is a property of the
    // theme, not of the nav bar: an app with mode:'off' or an empty manifest
    // still gets its intensity applied.
    applyFx(cfg);

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

    // The applet dock, between __here and the gear. An applet is a property of
    // the BAR, like the gear, rather than one more destination among the groups
    // on the left. Created and appended here, before the single
    // document.body.appendChild below, so the whole bar still enters the DOM in
    // one insertion -- NAV.slot is published only once it is actually in the
    // document, which is what the registry's two paths switch on.
    var slot = el('div', C + '__slot');
    nav.appendChild(slot);

    // Rightmost, after __here: the gear is a property of the bar itself rather
    // than of any app in it, so it sits apart from the groups on the left.
    var prefs = readPrefs();
    nav.appendChild(buildSettings(nav, cfg, prefs));

    document.body.appendChild(nav);

    // AFTER the insertion, so the slot an applet renders into is already laid
    // out; and BEFORE the mode:'push' return below, so applets work in push
    // mode too. Publishing the slot is what flips register() from its queueing
    // path to its immediate one, so both lines below have to follow it.
    NAV.slot = slot;
    flushApplets();                 // whatever registered before the bar existed
    loadApplets(cfg.applets);       // and whatever the manifest names

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

    // AFTER autoHide, which installs HIDDEN as the resting state -- applying
    // the preference last is what lets it win.
    if (prefs.pinned) applyPinned(nav, true);
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
      // Pinned by the user: the bar does not move. Guarded at every hide path
      // rather than by uninstalling the listeners, so the gear can toggle it
      // back off live without a reload.
      if (nav.classList.contains(C + '--pinned')) return;
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
      if (nav.classList.contains(C + '--pinned')) return;
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

  function bootstrap() {
    // Order matters: the layers go in first so the boot sequence begins at
    // first paint rather than after a network round trip. start() then fetches
    // the manifest and applyFx() tunes what is already on screen.
    installFx();
    start();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})();
