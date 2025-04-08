import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets land inside the Python package so the wheel ships the UI.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/email_agent/web/dist", emptyOutDir: true, sourcemap: false },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
