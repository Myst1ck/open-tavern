"""Item CRUD and equip/unequip/use endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request

from open_tavern.api import guards
from open_tavern.api.runtime import get_storage, invalidate_state, session_lock_ctx
from open_tavern.api.schemas import (
    CreateItemRequest,
    ItemActionResponse,
    ItemListResponse,
    ItemResponse,
)
from open_tavern.character.items import BaseType, Item, ItemStats
from open_tavern.storage import Storage

router = APIRouter()


# ── Item Endpoints ────────────────────────────────────────────────────────────


@contextmanager
def _character_write_scope(storage: Storage, session_id: str, character_id: str):
    """Serialize an item mutation and re-check its rows under the lock.

    The per-session lock makes the existence checks and the write atomic with
    respect to a concurrent ``delete_session``, which would otherwise orphan
    the row; the checks run under the lock because a delete may already have
    been queued ahead of this request.
    """
    with session_lock_ctx(session_id):
        guards.ensure_session(storage, session_id)
        guards.require_character_id(storage, session_id, character_id)
        yield


def _set_equipped_flag(
    storage: Storage,
    session_id: str,
    character_id: str,
    item_id: str,
    *,
    equipped: bool,
) -> ItemActionResponse:
    """Shared body of the equip/unequip endpoints."""
    with _character_write_scope(storage, session_id, character_id):
        item = storage.load_item(session_id, character_id, item_id)
        if item is None:
            return ItemActionResponse(success=False, message="item not found")
        updated = replace(item, equipped=equipped)
        storage.update_item(session_id, character_id, updated)

    invalidate_state(session_id)
    verb = "equipped" if equipped else "unequipped"
    return ItemActionResponse(
        success=True,
        item=ItemResponse(**updated.to_dict()),
        message=f"Item '{item.name}' {verb}",
    )


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items",
    response_model=ItemActionResponse,
    status_code=201,
)
def create_item(
    session_id: str,
    character_id: str,
    body: CreateItemRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Create a new item for a character and persist it."""
    guards.enforce_rate_limit(request, guards.item_limiter, "item")

    with _character_write_scope(storage, session_id, character_id):
        try:
            item_type = BaseType(body.type) if body.type else BaseType.loot
        except ValueError as err:
            valid = ", ".join(t.value for t in BaseType)
            raise HTTPException(
                status_code=422,
                detail=f"Invalid item type '{body.type}'. Must be one of: {valid}",
            ) from err
        stats = ItemStats.from_dict(body.stats or {})
        item = Item(
            name=body.name,
            type=item_type,
            stats=stats,
            tags=tuple(body.tags or []),
            description=body.description or "",
        )
        storage.save_item(session_id, character_id, item)

    invalidate_state(session_id)
    return ItemActionResponse(
        success=True,
        item=ItemResponse(**item.to_dict()),
        message=f"Item '{item.name}' created",
    )


@router.get(
    "/sessions/{session_id}/characters/{character_id}/items",
    response_model=ItemListResponse,
)
def list_items(
    session_id: str,
    character_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemListResponse:
    """Return all items for a character."""
    guards.enforce_rate_limit(request, guards.read_limiter, "read")
    guards.ensure_session(storage, session_id)
    guards.require_character_id(storage, session_id, character_id)

    items = storage.load_items(session_id, character_id)
    return ItemListResponse(items=[ItemResponse(**item.to_dict()) for item in items])


@router.get(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}",
    response_model=ItemResponse,
)
def get_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemResponse:
    """Return a single item by id."""
    guards.enforce_rate_limit(request, guards.read_limiter, "read")
    guards.ensure_session(storage, session_id)
    guards.require_character_id(storage, session_id, character_id)

    item = storage.load_item(session_id, character_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return ItemResponse(**item.to_dict())


@router.delete(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}",
    response_model=ItemActionResponse,
)
def delete_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Delete an item by id."""
    guards.enforce_rate_limit(request, guards.item_limiter, "item")

    with _character_write_scope(storage, session_id, character_id):
        deleted = storage.delete_item(session_id, character_id, item_id)

    invalidate_state(session_id)
    if not deleted:
        return ItemActionResponse(success=False, message="item not found")
    return ItemActionResponse(success=True, message="item deleted")


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}/equip",
    response_model=ItemActionResponse,
)
def equip_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Set item equipped=true."""
    guards.enforce_rate_limit(request, guards.item_limiter, "item")
    return _set_equipped_flag(storage, session_id, character_id, item_id, equipped=True)


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}/unequip",
    response_model=ItemActionResponse,
)
def unequip_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Set item equipped=false."""
    guards.enforce_rate_limit(request, guards.item_limiter, "item")
    return _set_equipped_flag(
        storage, session_id, character_id, item_id, equipped=False
    )


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}/use",
    response_model=ItemActionResponse,
)
def use_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Use a consumable item — decrement quantity or delete when depleted."""
    guards.enforce_rate_limit(request, guards.item_limiter, "item")

    with _character_write_scope(storage, session_id, character_id):
        item = storage.load_item(session_id, character_id, item_id)
        if item is None:
            return ItemActionResponse(success=False, message="item not found")
        if item.type != BaseType.consumable:
            return ItemActionResponse(
                success=False,
                item=ItemResponse(**item.to_dict()),
                message=f"Item '{item.name}' is not consumable",
            )
        if item.quantity > 1:
            used = replace(item, quantity=item.quantity - 1)
            storage.update_item(session_id, character_id, used)
        else:
            storage.delete_item(session_id, character_id, item_id)
            invalidate_state(session_id)
            return ItemActionResponse(
                success=True,
                item=None,
                message=f"Item '{item.name}' used and depleted",
            )

    invalidate_state(session_id)
    return ItemActionResponse(
        success=True,
        item=ItemResponse(**used.to_dict()),
        message=f"Item '{item.name}' used",
    )
