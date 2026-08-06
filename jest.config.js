/**
 * Root aggregator for the repo's infra chaos/DR test suites.
 *
 * Each component keeps its OWN jest.config.js (a Jest "project"); this root config just
 * links them together so one command runs them all. Add new suites to `projects` as they
 * land (progressive linking).
 *
 *   npm install            # once (installs jest at the repo root)
 *   npm test               # run every suite (destructive scenarios stay skipped)
 *   npm run test:dr        # include the destructive chaos scenarios (⚠️ disrupts live infra)
 *   npm test -- --selectProjects pihole-dr    # just one suite
 */
module.exports = {
  projects: [
    "<rootDir>/infrastructure/base/pihole/tests",
    // "<rootDir>/infrastructure/base/vpn-gateway/tests", // ← VPN rotator DR (next)
  ],
};
