/** VPN gateway/rotator chaos/DR suite — stateful, hits a live cluster → run serially. */
module.exports = {
  displayName: "vpn-dr", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 300000,
  maxWorkers: 1,
};
