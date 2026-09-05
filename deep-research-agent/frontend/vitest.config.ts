import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    css: true,
    include: ["**/*.{test,spec}.{ts,tsx}"],
    alias: {
      // Resolve `@` from the config file's own location so it works on any machine.
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
});
