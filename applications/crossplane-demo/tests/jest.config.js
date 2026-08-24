/** crossplane-demo provisioning integration suite — hits a live cluster → run serially. */
module.exports = {
  displayName: "provisioning-demo",
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 300000, // waits on operator CRs becoming Ready
  maxWorkers: 1,
};
