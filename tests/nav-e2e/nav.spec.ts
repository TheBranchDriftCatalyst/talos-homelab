/**
 * Every link in the injected navbar, navigated in a real browser.
 *
 * WHY A BROWSER AND NOT curl. Measured on these exact 51 links: a plain
 * `curl -L` run reports 43 failures, ALL of them artefacts — the homelab CA is
 * not in curl's trust store, so it cannot follow the http->https hop. Re-run
 * with -k and 49 of 51 return 200. So an HTTP probe produces either a wall of
 * false alarms or, once you silence those, false confidence: the two failures
 * it still cannot see are the interesting ones.
 *
 *   - a link can return 200 and render nothing (SPA that threw on boot)
 *   - a link can return 200 and bounce you to a DIFFERENT registrable domain
 *     mid-auth, which breaks the OIDC state cookie (zip.talos00 does this: it
 *     redirects to an SSO flow whose redirect_uri is the PUBLIC host)
 *
 * Both are invisible to any status-code check and obvious in a browser.
 *
 * THE LINK LIST IS DERIVED, NOT WRITTEN DOWN. It comes from the same manifest
 * the navbar itself consumes, so this suite covers whatever the bar currently
 * advertises — add an app and it is covered on the next run, with nothing to
 * edit here. A hand-maintained list would drift from the bar, and the bar is
 * the thing under test.
 */
import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";

const MANIFEST =
  process.env.NAV_MANIFEST ??
  "http://grafana.talos00/catalyst/resources/catalyst-nav.json";

/** Hosts that are legitimately an SSO gate rather than a destination. */
const SSO_HOSTS = [/^auth\./];

/** Error pages served BY THE INGRESS, i.e. nothing is behind the route. */
const INGRESS_ERROR = [/^404 page not found$/i, /^Bad Gateway$/i, /^Service Unavailable$/i];

type Item = { group: string; name: string; url: string };

/**
 * Fetched SYNCHRONOUSLY at module load, so each link becomes its own test()
 * rather than one test with a loop inside it. That is what gives per-link
 * pass/fail in the report, a per-link screenshot, and the ability to re-run a
 * single broken app with `-g "Zipline"`.
 *
 * A cache-buster is mandatory: the asset route serves the manifest with
 * stale-while-revalidate=3600, so without it a run can test the link list from
 * an hour ago. Add themepark's two replicas, each with its own sidecar, and
 * consecutive fetches can even disagree with each other.
 */
function loadItems(): Item[] {
  const sep = MANIFEST.includes("?") ? "&" : "?";
  const raw = execFileSync(
    "curl",
    ["-sk", "-m", "20", "-H", "Cache-Control: no-cache", `${MANIFEST}${sep}cb=${Date.now()}`],
    { encoding: "utf8", maxBuffer: 8 << 20 },
  );
  const nav = JSON.parse(raw);
  const out: Item[] = [];
  for (const g of nav.groups ?? []) {
    for (const i of g.items ?? []) {
      if (!i.href) continue;
      // The manifest stores protocol-relative hrefs ("//plex.talos00/") because
      // the bar is injected into both http and https pages.
      out.push({ group: g.name, name: i.name, url: i.href.startsWith("//") ? `http:${i.href}` : i.href });
    }
  }
  return out;
}

const items = loadItems();

test.beforeAll(() => {
  // A manifest that fetched but parsed to nothing would otherwise produce a
  // green run of zero tests, which reads identically to "everything passed".
  expect(items.length, `no nav items parsed from ${MANIFEST}`).toBeGreaterThan(10);
});

async function describePage(page: Page) {
  return page.evaluate(() => {
    const body = document.body;
    return {
      href: location.href,
      host: location.host,
      title: (document.title || "").trim(),
      text: (body?.innerText || "").trim().slice(0, 400),
      elements: body ? body.querySelectorAll("*").length : 0,
    };
  });
}

/** eTLD+1, good enough for talos00 / knowledgedump.space / amberdark.net. */
function registrable(host: string): string {
  const p = host.split(":")[0].split(".");
  return p.length <= 2 ? p.join(".") : p.slice(-2).join(".");
}

for (const item of items) {
  test(`${item.group} › ${item.name}`, async ({ page }, testInfo) => {
    const consoleErrors: string[] = [];
    page.on("console", m => {
      if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
    });

    const response = await page.goto(item.url, { waitUntil: "domcontentloaded" });

    // SPAs paint after domcontentloaded. networkidle is unreliable on pages
    // holding a websocket open (several of these do), so settle on the DOM.
    await page.waitForTimeout(1200);
    const info = await describePage(page);

    // Attached unconditionally: on a failure the report should show what the
    // page actually was, not just an assertion message. This is also the hook
    // the eventual visual snapshots plug into.
    await testInfo.attach("page.json", {
      body: JSON.stringify({ ...info, status: response?.status(), consoleErrors }, null, 2),
      contentType: "application/json",
    });

    const status = response?.status() ?? 0;
    const isSso = SSO_HOSTS.some(re => re.test(info.host));

    // 1. The ingress must have something behind the route.
    expect(status, `${item.url} returned HTTP ${status}`).toBeLessThan(400);

    // 2. The ingress's own error bodies are served WITH a 200 in some setups,
    //    so match the body too rather than trusting the status alone.
    for (const re of INGRESS_ERROR) {
      expect(info.text, `${item.url} served an ingress error page`).not.toMatch(re);
    }

    // 3. Something rendered. An SPA that threw on boot returns 200 with an
    //    empty body, which no status check can distinguish from working.
    expect(
      info.elements,
      `${item.url} rendered an essentially empty document (${info.elements} elements, ` +
        `${info.text.length} chars of text) — 200 but blank`,
    ).toBeGreaterThan(5);

    // 4. An SSO gate is a legitimate destination. Landing on a DIFFERENT
    //    registrable domain than you started on is NOT by itself a fault —
    //    nearly every app here sits behind an Authentik forward-auth outpost
    //    that redirects to auth.knowledgedump.space, and those work, because
    //    the outpost keeps its state server-side rather than in a cookie the
    //    callback has to carry. An earlier version of this assertion compared
    //    the two domains and flagged 41 of 51 HEALTHY links.
    //
    //    What actually breaks is a flow that sends you BACK to a different host
    //    than the one you clicked: state scoped to the original host is lost, a
    //    SameSite=Lax cookie set on the callback is dropped, and the operator
    //    silently lands on an origin the link never promised.
    //
    //    So compare the flow's own redirect_uri against the link's host. That
    //    passes forward-auth (sonarr.talos00 -> a callback on sonarr.talos00)
    //    and fails zip.talos00, whose flow points at zipline.knowledgedump.space.
    if (isSso) {
      const linkHost = new URL(item.url).host;
      const redirectUri = new URL(info.href).searchParams.get("redirect_uri");
      if (redirectUri) {
        const back = new URL(redirectUri).host;
        expect(
          back,
          `${item.url} starts an SSO flow that returns to a DIFFERENT host: clicked ` +
            `${linkHost}, redirect_uri points at ${back}. The operator ends up on an ` +
            `origin the link did not promise, and state scoped to ${linkHost} is lost.`,
        ).toBe(linkHost);
      }
    }
  });
}
