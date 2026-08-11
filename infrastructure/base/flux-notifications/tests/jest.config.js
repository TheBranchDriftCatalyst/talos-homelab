/** Discord notification webhook — integration suite (resolves the URL + optionally sends a real message). */
module.exports = {
  displayName: "discord-webhook", // labels this suite when run via the root aggregator
  testEnvironment: "node",
  testMatch: ["**/*.test.js"],
  testTimeout: 30000,
  maxWorkers: 1,
};
