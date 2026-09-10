import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.MAF_API_PROXY_TARGET ?? "http://127.0.0.1:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget
    }
  }
});
