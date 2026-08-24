/** CNPG failover chaos/DR suite — stateful, hits a live cluster → run serially. */
module.exports = {
  displayName: "cnpg-dr", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 600000, // canary bring-up + real failover promotion can take minutes
  maxWorkers: 1,
  reporters: ["default"],
};
