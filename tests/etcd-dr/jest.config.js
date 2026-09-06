/** Chaos/DR tests are stateful and hit a live cluster — always run serially. */
module.exports = {
  displayName: "etcd-dr", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 600000, // talosctl etcd snapshot of a real control-plane db is slow
  maxWorkers: 1,
  reporters: ["default"],
};
