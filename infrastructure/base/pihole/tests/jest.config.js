/** Chaos/DR tests are stateful and hit a live cluster — always run serially. */
module.exports = {
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 300000, // DR scenarios wait on real failover
  maxWorkers: 1,
  reporters: ["default"],
};
