import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Frontend na :5173, zapytania /api przekazywane do backendu FastAPI.
// Port backendu musi być ten sam co w skrypcie "dev:api" w package.json (domyślnie 8000; zmiana: API_PORT=...).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const apiPort: string = (globalThis as any).process?.env?.API_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true } },
  },
});
