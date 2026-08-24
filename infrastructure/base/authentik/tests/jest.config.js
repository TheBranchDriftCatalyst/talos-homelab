/** Authentik SSO chaos/DR suite — stateful, hits a live cluster → run serially. */
module.exports = {
  displayName: "authentik-dr", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 300000, // DR scenarios wait on a real authentik-server cold start
  maxWorkers: 1,
  reporters: ["default"],
};
