import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxies /api to the local FastAPI server, so the browser sees one origin
// and no CORS is involved. In production VITE_API_BASE points at the deployed API.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: true },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/data": { target: "http://localhost:8000", changeOrigin: true },
      "/img": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
