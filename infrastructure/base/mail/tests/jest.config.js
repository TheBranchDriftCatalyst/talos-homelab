/** Mail relay (Stalwart → Gmail) — integration scaffold. Sends a real email when gated; hits a live cluster → serial. */
module.exports = {
  displayName: "mail-relay", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 90000,
  maxWorkers: 1,
};
