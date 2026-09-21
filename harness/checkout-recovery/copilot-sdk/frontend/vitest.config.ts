import { defineConfig } from "vitest/config";

export default defineConfig({
  envDir: false,
  envPrefix: [],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "tests/config/**/*.test.ts"]
  }
});
