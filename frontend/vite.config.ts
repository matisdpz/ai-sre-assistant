import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the browser talks only to Vite, which forwards API calls to the
// backend: same origin, so no CORS configuration is needed (nginx does the same in Docker).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
