/**
 * Cowrie honeypot security-posture tests.
 *
 * Unlike the DR suites these are NOT destructive and touch nothing — every check is a
 * read-only query against the live cluster. They exist because this workload is about to be
 * deliberately exposed to the internet, and the controls that make that survivable are easy
 * to regress silently.
 */
module.exports = {
  displayName: "honeypot-security",
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 120000,
  maxWorkers: 1,
  reporters: ["default"],
};
