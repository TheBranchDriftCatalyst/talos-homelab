/**
 * Root aggregator for the repo's infra chaos/DR test suites.
 *
 * Each component keeps its OWN jest.config.js (a Jest "project"); this root config just
 * links them together so one command runs them all. Add new suites to `projects` as they
 * land (progressive linking).
 *
 *   npm install            # once (installs jest at the repo root)
 *   npm test               # interactive picker — choose suites + flags (scripts/jest-select.js)
 *   npm run test:all       # run every suite non-interactively (destructive scenarios stay skipped)
 *   npm run test:dr        # include the destructive chaos scenarios (⚠️ disrupts live infra)
 *   npm test -- --selectProjects pihole-dr    # args bypass the picker → straight to jest
 */
module.exports = {
  projects: [
    "<rootDir>/infrastructure/base/pihole/tests",
    "<rootDir>/infrastructure/base/vpn-gateway/tests",
    "<rootDir>/applications/crossplane-demo/tests",
    "<rootDir>/infrastructure/base/flux-notifications/tests", // discord-webhook integration
    "<rootDir>/infrastructure/base/mail/tests", // mail-relay integration (scaffold until Stalwart lands)
    "<rootDir>/infrastructure/base/backup/tests", // velero backup/restore DR (TALOS-23l.1)
    "<rootDir>/infrastructure/base/minio/tests", // MinIO NFS-backed S3 persistence DR (TALOS-23l.2)
    "<rootDir>/infrastructure/base/cilium/tests", // Cilium LB-IPAM / L2 VIP failover DR (TALOS-23l.3)
  ],
};
