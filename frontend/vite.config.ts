import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      // Instead of browser CORS - use a dev-server proxy
      "/api": {
        target: "http://backend:8000",
        changeOrigin: true,
      },
    },
  },
});

