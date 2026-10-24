# nav-e2e — every navbar link, navigated in a real browser

```bash
cd tests/nav-e2e
npm install && npx playwright install chromium   # first run only
npx playwright test                              # all links
npx playwright test -g "Zipline"                 # one app
npx playwright show-report .artifacts/html
```

The link list is **derived from the live nav manifest**, the same one the bar
consumes — add an app and it is covered on the next run with nothing to edit
here. One `test()` per link, so the report names the broken app and a screenshot
lands next to it.

## Why a browser and not curl

Measured on these 51 links:

| probe | result |
|---|---|
| `curl -L` | 43 "failures" — **all artefacts**, curl has no homelab CA so it cannot follow the http→https hop |
| `curl -kL` | 49/51 return 200 |
| this suite | 48/51 pass, and the 3 are real |

So a status-code probe gives either a wall of false alarms or, once silenced,
false confidence. The two things it structurally cannot see:

- **200 with nothing rendered** — an SPA that threw on boot
- **an SSO flow that returns you to a different host than you clicked**

## The four assertions

1. HTTP status < 400.
2. The body is not an ingress error page (some setups serve those with a 200).
3. Something actually rendered (>5 elements) — catches "200 but blank".
4. If the flow lands on SSO, its `redirect_uri` must point back at the host you
   clicked.

Assertion 4 is deliberately **not** "did we change domain". An earlier version
compared registrable domains and flagged **41 of 51 healthy links**: nearly
everything here sits behind an Authentik forward-auth outpost on
`auth.knowledgedump.space`, and that works, because the outpost keeps state
server-side. What breaks is being returned to a *different host*, which is what
`zip.talos00` does.

## workers: 1 is a measurement, not caution

At `workers: 6` this suite reports 12–27 failures that change run to run; at
`workers: 1` it reports 3. The difference is not the apps — ~40 of these links
share ONE forward-auth outpost, and concurrent auth flows against it return
HTTP 400. Raising workers is a useful **load test of the outpost**; it is not a
link check. Keep them separate.
