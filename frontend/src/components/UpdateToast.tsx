import { useRegisterSW } from "virtual:pwa-register/react";

export default function UpdateToast() {
  const {
    offlineReady: [offlineReady, setOfflineReady],
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW();

  const close = () => {
    setOfflineReady(false);
    setNeedRefresh(false);
  };

  const refresh = async () => {
    await updateServiceWorker(true);
    close();
  };

  if (!offlineReady && !needRefresh) {
    return null;
  }

  return (
    <div className="update-toast" role="status">
      <span className="update-toast-message">
        {needRefresh ? "New version available" : "App ready to work offline"}
      </span>
      {needRefresh && (
        <button type="button" className="update-toast-action" onClick={refresh}>
          Refresh
        </button>
      )}
      <button
        type="button"
        className="update-toast-close"
        onClick={close}
        aria-label="Dismiss"
      >
        ×
      </button>
    </div>
  );
}
