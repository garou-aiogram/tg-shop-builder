import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Локальная разработка: API и медиа проксируются на backend
    proxy: { "/api": "http://localhost:8000", "/media": "http://localhost:8000" },
  },
});
