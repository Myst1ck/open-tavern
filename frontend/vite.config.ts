import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Vite loads this config in Node, where `process` is a global. Declared here so
// `tsc -b` type-checks without pulling in @types/node.
declare const process: { env: Record<string, string | undefined> };

// Dev PWA served under a subpath (https://brain.ts.net/tavern via tailscale serve).
// Container prod serves at root; both are env-driven so one config covers both.
const base = process.env.VITE_BASE ?? "/tavern/";

const proxyTarget = process.env.OPEN_TAVERN_PROXY_TARGET ?? "http://127.0.0.1:8000";

const backendProxy = {
  "/sessions": proxyTarget,
  "/world": proxyTarget,
};

export default defineConfig({
  base,
  plugins: [
    react(),
    VitePWA({
      strategies: "generateSW",
      registerType: "prompt",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: process.env.VITE_PWA_NAME ?? "Tavern Dev",
        short_name: "Tavern",
        description: "Open Tavern — a local-first AI roleplay tavern.",
        display: "standalone",
        start_url: base,
        scope: base,
        theme_color: "#1a120b",
        background_color: "#1a120b",
        icons: [
          {
            src: "pwa-192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "pwa-512.png",
            sizes: "512x512",
            type: "image/png",
          },
          {
            src: "pwa-512-maskable.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        navigateFallback: "index.html",
        runtimeCaching: [
          {
            urlPattern: /^\/(sessions|world)\b/,
            method: "GET",
            handler: "NetworkFirst",
            options: {
              cacheName: "api-cache",
              expiration: {
                maxAgeSeconds: 300,
                maxEntries: 60,
              },
              cacheableResponse: {
                statuses: [200],
              },
            },
          },
        ],
      },
      devOptions: {
        enabled: true,
        // With base '/tavern/', dev serves the app at /tavern/ (and
        // /tavern/index.html); allowlist must match those navigations.
        navigateFallbackAllowlist: [new RegExp(`^${base}(index\\.html)?$`)],
      },
    }),
  ],
  server: {
    allowedHosts: ["brain", ".ts.net"],
    proxy: backendProxy,
  },
  preview: {
    allowedHosts: ["brain", ".ts.net"],
    proxy: backendProxy,
  },
});
