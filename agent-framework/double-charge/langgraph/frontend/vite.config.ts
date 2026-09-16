import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { serverConfig } from "./server-config";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  envDir: false as const,
  envPrefix: [],
  server: mode === "test" ? serverConfig({}) : serverConfig(),
  test: {
    environment: "jsdom",
    setupFiles: "./tests/setup.ts",
    include: ["tests/*.test.ts", "tests/*.test.tsx"],
    server: {
      deps: {
        inline: ["@copilotkit/react-core"]
      }
    }
  }
}));
