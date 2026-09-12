/**
 * Root aggregator for the repo's remaining Jest suites.
 *
 * NOTE: the Disaster-Recovery suites migrated to pytest (suite marker `disaster_recovery`; run
 * with `task test:dr` / `pytest -m disaster_recovery`). See TESTING.md. Only the suites that have
 * NOT yet been ported remain here:
 *   - traefik-dr / vpn-dr  — still Jest DR suites; their directories are currently owned by another
 *     work-stream, so their pytest port is deferred (tracked as follow-up).
 *   - discord-webhook / mail-relay / crossplane provisioning / honeypot-security — non-DR
 *     integration/posture suites, out of scope for the DR migration.
 *
 * Each component keeps its OWN jest.config.js (a Jest "project"); this root config links them so
 * one command runs them all.
 *
 *   npm test               # interactive picker — choose suites + flags (scripts/jest-select.js)
 *   npm run test:all       # run every remaining suite non-interactively
 *   npm run test:dr        # include the surviving destructive DR scenarios (⚠️ disrupts live infra)
 *   npm test -- --selectProjects traefik-dr    # args bypass the picker → straight to jest
 */
module.exports = {
  projects: [
    "<rootDir>/infrastructure/base/vpn-gateway/tests", // WireGuard VPN gateway DR (Jest; pytest port deferred)
    "<rootDir>/infrastructure/base/traefik/tests", // Traefik ingress SPOF failover DR (Jest; pytest port deferred, TALOS-23l.8)
    "<rootDir>/applications/crossplane-demo/tests", // crossplane provisioning integration (non-DR)
    "<rootDir>/infrastructure/base/flux-notifications/tests", // discord-webhook integration (non-DR)
    "<rootDir>/infrastructure/base/mail/tests", // mail-relay integration scaffold (non-DR)
    "<rootDir>/infrastructure/base/honeypot/tests", // Cowrie honeypot security posture (non-DR, TALOS-hg7)
  ],
};
