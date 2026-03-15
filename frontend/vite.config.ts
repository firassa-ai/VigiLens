import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const backendPort = process.env.BACKEND_PORT ?? "8000";
const proxyHttpTarget = process.env.VITE_DEV_PROXY_TARGET ?? `http://localhost:${backendPort}`;
const proxyWsTarget = process.env.VITE_DEV_PROXY_WS_TARGET ?? `ws://localhost:${backendPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: Number(process.env.FRONTEND_PORT ?? 3000),
    proxy: {
      "/api": {
        target: proxyHttpTarget,
        changeOrigin: true,
      },
      "/ws": {
        target: proxyWsTarget,
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
  },
});
