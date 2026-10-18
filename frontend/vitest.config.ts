import path from "path";
import { defineConfig } from "vitest/config";

// Plain Vitest config, not Next's plugin wrapper — these are unit/component
// tests (lib helpers, shared components), not full Next route rendering.
// Keep the "@/*" alias in sync with tsconfig.json's `paths`.
export default defineConfig({
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
