import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  // three.js/R3F are split automatically into the lazily imported OfficeScene chunk.
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"] },
});
