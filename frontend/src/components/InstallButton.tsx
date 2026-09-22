import { useEffect, useState } from "react";

import { type BeforeInstallPromptEvent, deferredPrompt } from "../main";

function isIos(): boolean {
  if (typeof navigator === "undefined") {
    return false;
  }
  const ua = navigator.userAgent;
  const platform = navigator.platform ?? "";
  // iPadOS reports itself as MacIntel; touch points disambiguate it.
  const isIpadOs = platform === "MacIntel" && navigator.maxTouchPoints > 1;
  return /iPad|iPhone|iPod/.test(ua) || isIpadOs;
}

function isStandalone(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.matchMedia("(display-mode: standalone)").matches;
}

export default function InstallButton() {
  const [canInstall, setCanInstall] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [iosHint, setIosHint] = useState(false);

  useEffect(() => {
    if (isStandalone()) {
      setInstalled(true);
      return;
    }

    // The prompt may have fired before React mounted (cold load); the module
    // scope listener in main.tsx captured it.
    if (deferredPrompt.current !== null) {
      setCanInstall(true);
    }

    const onBeforeInstallPrompt = (event: Event) => {
      deferredPrompt.current = event as BeforeInstallPromptEvent;
      setCanInstall(true);
    };

    const onAppInstalled = () => {
      deferredPrompt.current = null;
      setCanInstall(false);
      setInstalled(true);
    };

    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    window.addEventListener("appinstalled", onAppInstalled);

    // iOS Safari never fires beforeinstallprompt; show manual instructions.
    if (isIos()) {
      setIosHint(true);
    }

    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
      window.removeEventListener("appinstalled", onAppInstalled);
    };
  }, []);

  const handleInstall = async () => {
    const deferred = deferredPrompt.current;
    if (deferred === null) {
      return;
    }
    try {
      await deferred.prompt();
      await deferred.userChoice;
    } catch {
      // Prompt can reject (e.g. already installed, user gesture lost).
    } finally {
      deferredPrompt.current = null;
      setCanInstall(false);
    }
  };

  if (installed) {
    return null;
  }

  if (canInstall) {
    return (
      <button
        type="button"
        className="install-button"
        onClick={handleInstall}
      >
        Install app
      </button>
    );
  }

  if (iosHint) {
    return (
      <span className="install-hint">
        Install: Share &gt; Add to Home Screen
      </span>
    );
  }

  return null;
}