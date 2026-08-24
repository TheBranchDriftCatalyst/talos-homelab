/** Chaos/DR tests are stateful and hit a live cluster — always run serially. */
module.exports = {
  displayName: "cilium-lbipam-dr", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 300000, // DR scenarios wait on real L2 re-announcement / lease re-election
  maxWorkers: 1,
  reporters: ["default"],
};
