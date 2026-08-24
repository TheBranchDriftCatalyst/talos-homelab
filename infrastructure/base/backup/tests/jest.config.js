/** Chaos/DR tests are stateful and hit a live cluster — always run serially. */
module.exports = {
  displayName: "velero-dr", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 600000, // real backup+restore round-trips (kopia fs-backup) are slow
  maxWorkers: 1,
  reporters: ["default"],
};
