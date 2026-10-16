import { cachedSettings, settingsHeaders } from "./settings";

// API calls are same-origin. When the app is served under a subpath (e.g.
// /tavern/ via tailscale serve), Vite's BASE_URL carries that prefix, so
// absolute paths like /world/generate become /tavern/world/generate.
// VITE_API_BASE_URL overrides this for split-origin deployments.
const DEFAULT_BASE_URL = import.meta.env.BASE_URL;

const API_BASE_URL = (() => {
  const raw = (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL).replace(
    /\/+$/,
    "",
  );
  // Root serving yields "" or "/" — both mean no prefix.
  return raw === "/" ? "" : raw;
})();

/** Abort in-flight fetches after this long to avoid hanging requests. */
const REQUEST_TIMEOUT_MS = 30_000;

/**
 * LLM-backed endpoints can take far longer than cheap reads; give them a
 * generous ceiling so generation is not aborted mid-flight.
 */
export const LLM_TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...settingsHeaders(cachedSettings),
        ...Object.fromEntries(new Headers(init.headers)),
      },
    });
    if (!response.ok) {
      throw new ApiError(response.status, await errorDetail(response));
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  } catch (err) {
    // The timer aborts the fetch; surface a readable message instead of the
    // raw DOMException text ("signal is aborted without reason").
    if (controller.signal.aborted) {
      throw new ApiError(
        0,
        "Request timed out — the storyteller took too long. Try again.",
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Non-JSON error body; fall through to the status text.
  }
  // ``statusText`` is empty on HTTP/2, which would surface a blank error.
  return response.statusText !== ""
    ? response.statusText
    : `Request failed (HTTP ${response.status})`;
}
