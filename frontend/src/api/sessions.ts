import { request } from "./http";
import type {
  DmStyle,
  Session,
  SessionDetail,
  SessionSummary,
  StateResponse,
} from "./types";

export function createSession(
  worldTheme: string,
  title?: string,
  premise?: string,
  dmStyle?: DmStyle,
): Promise<Session> {
  return request<Session>("/sessions", {
    method: "POST",
    body: JSON.stringify({
      world_theme: worldTheme,
      ...(title !== undefined ? { title } : {}),
      ...(premise !== undefined ? { premise } : {}),
      ...(dmStyle !== undefined ? { dm_style: dmStyle } : {}),
    }),
  });
}

export function listSessions(): Promise<SessionSummary[]> {
  return request<SessionSummary[]>("/sessions");
}

export function getSession(id: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/sessions/${id}`);
}

export function renameSession(
  id: string,
  title: string,
): Promise<SessionSummary> {
  return request<SessionSummary>(`/sessions/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteSession(id: string): Promise<void> {
  return request<void>(`/sessions/${id}`, { method: "DELETE" });
}

/**
 * Replace the session's DM narration style mid-game. The backend validates
 * preset keys (422 on unknown) and echoes the normalized style.
 */
export function updateSessionStyle(
  sessionId: string,
  style: DmStyle,
): Promise<DmStyle> {
  return request<DmStyle>(`/sessions/${sessionId}/style`, {
    method: "PUT",
    body: JSON.stringify(style),
  });
}

export function getState(sessionId: string): Promise<StateResponse> {
  return request<StateResponse>(`/sessions/${sessionId}/state`);
}
