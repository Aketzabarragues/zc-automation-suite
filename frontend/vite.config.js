import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

/**
 * Vite dev del frontend. El backend Flask corre aparte (ver `iniciar.py`).
 * En dev, todo lo que empieza por /api se redirige al backend; el resto lo
 * sirve Vite. En produccion (build) el backend sirve `frontend/dist`.
 */
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:9484",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.spec.js"],
  },
});
