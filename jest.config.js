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
    "<rootDir>/infrastructure/base/cilium/tests",
    "<rootDir>/infrastructure/base/honeypot/tests", // Cowrie honeypot security posture — guards the controls that make deliberate internet exposure survivable (TALOS-hg7) // Cilium LB-IPAM / L2 VIP failover DR (TALOS-23l.3)
    "<rootDir>/infrastructure/base/authentik/tests", // Authentik SSO SPOF recovery DR (TALOS-23l.4)
    "<rootDir>/infrastructure/base/databases/tests", // CloudNativePG primary failover DR (TALOS-23l.5)
    "<rootDir>/infrastructure/base/talos-dr/tests", // etcd snapshot freshness + integrity DR (TALOS-23l.6)
    "<rootDir>/infrastructure/base/storage/tests", // NFS/local-path PVC reuse lifecycle DR (TALOS-23l.7)
    "<rootDir>/infrastructure/base/traefik/tests", // Traefik ingress SPOF failover DR (TALOS-23l.8)
  ],
};
