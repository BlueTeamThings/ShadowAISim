const { defineConfig } = require("vitest/config");

module.exports = defineConfig({
  test: {
    include: ["tests/unit/**/*.test.js"],
    environment: "jsdom",
    globals: true,
  },
});
