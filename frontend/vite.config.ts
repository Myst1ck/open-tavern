import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backendProxy = {
  "/sessions": "http://127.0.0.1:8000",
  "/world": "http://127.0.0.1:8000",
};

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ["brain", ".ts.net"],
    proxy: backendProxy,
  },
  preview: {
    allowedHosts: ["brain", ".ts.net"],
    proxy: backendProxy,
  },
});
