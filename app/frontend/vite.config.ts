import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8000",
      "/status": "http://127.0.0.1:8000",
      "/chat": "http://127.0.0.1:8000",
      "/retrieve": "http://127.0.0.1:8000",
      "/personas": "http://127.0.0.1:8000",
      "/documents": "http://127.0.0.1:8000",
      "/chunks": "http://127.0.0.1:8000",
      "/eval": "http://127.0.0.1:8000",
      "/traces": "http://127.0.0.1:8000"
    }
  }
});
