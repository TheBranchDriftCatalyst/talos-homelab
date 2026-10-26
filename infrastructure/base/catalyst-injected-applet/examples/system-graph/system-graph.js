/* system-graph — catalyst navbar applet (TALOS-gsgh.5)
 * ============================================================================
 * REFERENCE ARTIFACT — NOT served from talos-homelab. Its real home is the
 * system-graph frontend (the human-edited demo/ tree, from which server/web/ is
 * derived by scripts/sync-web.sh and embed.go embeds it). The orchestrator folds
 * it in there — DO NOT hand-edit demo/app.js; this is a NEW, separate file.
 *
 *   DESTINATION (suggested):  system-graph/demo/system-graph-applet.js
 *   SERVED AT:                /catalyst/applets/system-graph/system-graph.js
 *
 * ...which requires the system-graph Go server to be PREFIX-AWARE: it must serve
 * this file (and the UI, and /api/graph) under the /catalyst/applets/system-graph/
 * and /catalyst/api/system-graph/ mounts the CatalystInjectedApplet claim routes to
 * it. See this directory's README for the exact server change. Until then the claim's
 * routes 404 and the nav loader drops this bundle silently (by design).
 *
 * WHAT IT DOES. An applet cannot inject itself — there is exactly one rewriteBody on
 * these pages (catalyst-nav) and a second one silently no-ops. So this rides inside the
 * nav: the bundle is <script defer>'d by catalyst-nav's loader, calls register(), and
 * gets one dock element in the bar. We dock a single button; clicking it opens a
 * full-viewport overlay whose body is an <iframe> pointing at the system-graph UI.
 *
 * WHY AN IFRAME, NOT AN INLINE RENDER. The system-graph UI is a full-page D3 SPA that
 * owns the whole document (a viewport-filling <svg id="graph">, ~40 fixed-id elements,
 * its own fonts and stylesheet). It is not a component that mounts into an arbitrary
 * node, and (per the dev-overlay design doc's catalyst-ui finding) dropping a whole app's
 * CSS/JS into ~40 host pages corrupts them. An iframe is the correct, minimal embed: it
 * isolates the SPA's DOM, CSS, globals and history from whatever host app we are inside.
 *
 * WHY SAME-ORIGIN (/catalyst/applets/system-graph/) AND NOT https://system-graph.talos00/.
 * Same-origin under /catalyst/ is the one prefix gated by HostRegexp + lan-only and NOT by
 * authentik, so the iframe loads with no SSO redirect, no third-party-cookie question and
 * no X-Frame-Options/CSP frame-ancestors negotiation. A cross-origin src to the SSO host
 * would (a) need the authentik session cookie in a third-party iframe context — SameSite=Lax
 * cookies are NOT sent there, so it would hit the login flow — and (b) need framing headers
 * the app does not send today. See the README's "interim cross-origin fallback" if the
 * server prefix work is not ready.
 *
 * EVERYTHING HERE IS SILENT AND DEFENSIVE. This runs inside applications we did not write;
 * a throw must never corrupt a host page. register()'s own try/catch is the outer net; the
 * inner guards here keep a second click, a missing global or a torn-down DOM from throwing.
 * ES5, no build step, no dependencies — same house style as catalyst-nav.js.
 * ========================================================================== */
(function () {
  "use strict";

  var NAV = window.__catalystNav;
  if (!NAV || typeof NAV.register !== "function") return; // loaded without the bar; nothing to dock into.

  var NAME = "system-graph";

  // Same-origin, under the gated /catalyst/ prefix. A trailing slash so the server's
  // prefix mount resolves the UI index. Switch to the cross-origin fallback ONLY per the
  // README (it reopens the SSO/framing problems this path avoids).
  var UI_SRC = "/catalyst/applets/system-graph/";

  // One id-prefix for everything we create, so the overlay is trivially found, deduped and
  // removed, and cannot collide with a host app's ids/classes.
  var P = "catalyst-sg-applet";

  // Graph glyph: three nodes (repo / app / db) and their edges. Inline SVG so the button
  // carries no dependency on an icon asset path. currentColor so it inherits the bar's ink.
  var ICON =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="5" cy="6" r="2.2"></circle>' +
    '<circle cx="19" cy="8" r="2.2"></circle>' +
    '<circle cx="12" cy="18" r="2.2"></circle>' +
    '<path d="M6.8 7.2 10.6 16M17.4 9.6 13.4 16.4M6.9 6.6 16.9 7.7"></path>' +
    "</svg>";

  var overlay = null; // the live overlay element, or null when closed.
  var onKey = null; // the Escape handler while open, so we can remove exactly it.

  function close() {
    try {
      if (onKey) {
        document.removeEventListener("keydown", onKey, true);
        onKey = null;
      }
      if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    } catch (e) {
      /* nothing to report to; see file header */
    }
    overlay = null;
  }

  function open() {
    if (overlay) return; // already open; a second click is a no-op, not a second iframe.

    overlay = document.createElement("div");
    overlay.id = P + "-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "System Graph");
    // Inline styles, not a stylesheet: a bare rule would sit inert on any page where this
    // bundle did not run, and we must add nothing to the host's cascade. z-index above the
    // nav bar (which sits very high itself); position fixed to cover the viewport.
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:2147483646;display:flex;" +
      "flex-direction:column;background:rgba(10,10,14,0.88);" +
      "backdrop-filter:blur(2px);-webkit-backdrop-filter:blur(2px);";

    // Header strip with a title and a close button.
    var bar = document.createElement("div");
    bar.style.cssText =
      "flex:0 0 auto;display:flex;align-items:center;gap:10px;" +
      "padding:8px 12px;font:600 13px/1.2 'Chakra Petch',system-ui,sans-serif;" +
      "color:#e6e6f0;background:#14141c;border-bottom:1px solid #2a2a3a;";

    var title = document.createElement("span");
    title.style.cssText = "display:flex;align-items:center;gap:8px;";
    title.innerHTML = ICON + "<span>System Graph</span>";

    var spacer = document.createElement("span");
    spacer.style.cssText = "flex:1 1 auto;";

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Close System Graph");
    closeBtn.textContent = "×"; // ×
    closeBtn.style.cssText =
      "cursor:pointer;border:0;background:transparent;color:#e6e6f0;" +
      "font-size:22px;line-height:1;padding:0 6px;border-radius:6px;";
    closeBtn.onmouseenter = function () { closeBtn.style.background = "#2a2a3a"; };
    closeBtn.onmouseleave = function () { closeBtn.style.background = "transparent"; };
    closeBtn.onclick = close;

    bar.appendChild(title);
    bar.appendChild(spacer);
    bar.appendChild(closeBtn);

    var frame = document.createElement("iframe");
    frame.src = UI_SRC;
    frame.title = "System Graph";
    frame.style.cssText = "flex:1 1 auto;width:100%;border:0;background:#0b0b10;";
    // Same-origin: no sandbox needed, and the SPA needs scripts + same-origin fetch to
    // /catalyst/api/system-graph/graph. (A cross-origin fallback src would need a sandbox
    // review — see the README.)

    overlay.appendChild(bar);
    overlay.appendChild(frame);

    // Click the dimmed margin (the overlay itself, never a child) to close.
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) close();
    });

    onKey = function (e) {
      if (e.key === "Escape" || e.keyCode === 27) {
        close();
        // Swallow Esc so the host app underneath does not also act on it while we are up.
        e.stopPropagation();
      }
    };
    document.addEventListener("keydown", onKey, true);

    (document.body || document.documentElement).appendChild(overlay);
  }

  // render(dock, nav) — called once by catalyst-nav with our own dock element already in
  // the bar. Build exactly one button; do not reach outside `dock`.
  function render(dock) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("aria-label", "Open System Graph");
    btn.title = "System Graph — live cluster topology";
    btn.innerHTML = ICON;
    btn.style.cssText =
      "display:inline-flex;align-items:center;justify-content:center;" +
      "width:28px;height:28px;cursor:pointer;border:0;border-radius:6px;" +
      "background:transparent;color:inherit;";
    btn.onmouseenter = function () { btn.style.background = "rgba(255,255,255,0.12)"; };
    btn.onmouseleave = function () { btn.style.background = "transparent"; };
    btn.onclick = open;
    dock.appendChild(btn);
  }

  NAV.register(NAME, render);
})();
