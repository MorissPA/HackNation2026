import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Frontend na :5173, zapytania /api przekazywane do backendu FastAPI na :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
