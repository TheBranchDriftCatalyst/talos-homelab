import { defineConfig } from "@playwright/test";

// Nav-link reachability against the LIVE cluster. Read tests/nav-e2e/README.md
// before changing anything here; several of these settings are load-bearing.
export default defineConfig({
  testDir: ".",
  // SERIAL ON PURPOSE. MEASURED, not cautious: at workers=6 this suite reports
  // 12-27 failures that vary run to run, and at workers=1 it reports 3. The
  // difference is not the apps — it is that ~40 of these links sit behind ONE
  // shared Authentik forward-auth outpost, and concurrent auth flows against it
  // return HTTP 400. A suite whose failure list changes every run teaches people
  // to ignore it, which is worse than not having it.
  //
  // Raising this is a useful LOAD TEST of the outpost, but it is not a link
  // check. Keep the two separate.
  workers: 1,
  fullyParallel: false,
  // No retries. A flaky nav link IS the finding — retrying would hide exactly
  // the intermittent breakage this suite exists to catch.
  retries: 0,
  timeout: 45_000,
  reporter: [["list"], ["html", { open: "never", outputFolder: ".artifacts/html" }]],
  outputDir: ".artifacts/results",
  use: {
    // THE HOMELAB CA IS NOT IN PLAYWRIGHT'S TRUST STORE. Without this every
    // https:// hop fails and the whole suite reports breakage that does not
    // exist — which is precisely what a plain `curl` run of these 51 links
    // reports (43 apparent failures, all of them TLS-verification noise).
    ignoreHTTPSErrors: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
});
