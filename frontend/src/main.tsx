import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";

/** Chromium-only event; not part of the standard TS DOM lib. */
export interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{
    outcome: "accepted" | "dismissed";
    platform: string;
  }>;
  prompt: () => Promise<void>;
}

/**
 * Deferred install prompt captured at module scope. The event can fire before
 * React mounts (cold loads), so the listener must attach before render or the
 * prompt is lost. InstallButton reads this holder on mount.
 */
export const deferredPrompt: { current: BeforeInstallPromptEvent | null } = {
  current: null,
};

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt.current = event as BeforeInstallPromptEvent;
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);