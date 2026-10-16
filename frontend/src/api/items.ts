import { request } from "./http";
import type { ItemActionResponse } from "./types";

export function deleteItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}`,
    { method: "DELETE" },
  );
}

export function equipItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}/equip`,
    { method: "POST" },
  );
}

export function unequipItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}/unequip`,
    { method: "POST" },
  );
}

export function useItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}/use`,
    { method: "POST" },
  );
}
