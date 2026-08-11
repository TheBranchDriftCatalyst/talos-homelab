/** Chaos/DR tests are stateful and hit a live cluster — always run serially. */
module.exports = {
  displayName: "minio-dr", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 600000, // DR scenarios kill the tenant pod + wait on the NFS-backed restart
  maxWorkers: 1,
  reporters: ["default"],
};
