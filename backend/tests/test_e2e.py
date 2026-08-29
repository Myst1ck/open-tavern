"""End-to-end integration test for the full play flow.

Drives the real FastAPI routes through :class:`fastapi.testclient.TestClient`
with a fake LLM client and an in-memory SQLite database. No network or disk
access: both dependencies are swapped in via ``app.dependency_overrides``.

The single test exercises the whole loop: create session -> generate
character -> send an action that triggers a CHECK + DAMAGE -> dice rolled by
the engine -> outcome narrated -> state updated -> session reloaded from the
same database and verified identical.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from open_tavern.api.main import create_app
from open_tavern.api.routes import get_client, get_storage
from open_tavern.storage import Storage

#: Raw character sheet the fake LLM returns for generation. Derived values
#: (modifiers, proficiency bonus, HP) are computed by code, never trusted here.
_VALID_SHEET: dict[str, object] = {
    "name": "Thorn",
    "race": "elf",
    "character_class": "fighter",
    "level": 2,
    "abilities": {"STR": 16, "DEX": 12, "CON": 14, "INT": 10, "WIS": 13, "CHA": 8},
    "skills": {"Athletics": True},
    "inventory": ["longsword"],
    "backstory": "A battle-hardened sellsword.",
}

#: STR 16 -> +3.
_STRENGTH_MODIFIER: int = (16 - 10) // 2
#: fighter (default d8), level 2, CON 14 (+2): 8 + 2 + (5 + 2) = 17.
_MAX_HP: int = 17

_FOLLOW_UP_NARRATION: str = "You slip past the goblin's guard and drive it back."


class FakeLLMClient:
    """Content-driven fake chat client that never touches the network.

    Routes by prompt content rather than call order, so one instance serves all
    three phases of the flow:

    * ``json_mode=True`` -> character JSON (character generation).
    * last message is the roll-result follow-up -> outcome narration.
    * otherwise (first turn) -> narration requesting a check + damage.
    """

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        self.calls.append(messages)
        if json_mode:
            return json.dumps(_VALID_SHEET)
        last = messages[-1]["content"]
        if "The dice have been rolled" in last:
            return _FOLLOW_UP_NARRATION
        return "You surge forward to strike. [CHECK:strength DC12] [DAMAGE:2d6]"


def test_full_flow_end_to_end() -> None:
    fake = FakeLLMClient()
    store = Storage(":memory:")
    store.init()
    try:
        app = create_app()
        app.dependency_overrides[get_storage] = lambda: store
        app.dependency_overrides[get_client] = lambda: fake
        client = TestClient(app)

        # 1. Create a session.
        resp = client.post("/sessions", json={"world_theme": "a haunted tavern"})
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]
        assert session_id

        # 2. Generate a character from a free-text description.
        resp = client.post(
            f"/sessions/{session_id}/character",
            json={"description": "a battle-hardened elf sellsword"},
        )
        assert resp.status_code == 200
        sheet = resp.json()["character"]
        assert sheet["name"] == "Thorn"
        assert sheet["character_class"] == "fighter"
        assert sheet["max_hp"] == _MAX_HP

        # 3. Send an action whose first GM response requests a check + damage.
        resp = client.post(
            f"/sessions/{session_id}/actions",
            json={"action": "attack the goblin"},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Outcome narration comes from the second (roll-result) phase.
        assert data["narration"] == _FOLLOW_UP_NARRATION

        # A single check roll was recorded with the expected shape.
        rolls = data["rolls"]
        assert len(rolls) == 1
        roll = rolls[0]
        assert roll["name"] == "strength"
        assert roll["dc"] == 12
        assert roll["modifier"] == _STRENGTH_MODIFIER
        assert roll["total"] == roll["d20"] + roll["modifier"]
        assert roll["success"] == (roll["total"] >= 12)

        # The 2d6 damage tag was actually rolled: HP dropped by 2..12.
        state = data["state"]
        hp_lost = state["max_hp"] - state["current_hp"]
        assert 2 <= hp_lost <= 12

        # The turn used two LLM calls (first + roll-result follow-up).
        assert len(fake.calls) == 3  # 1 character gen + 2 turn

        # 4. Reload from the same database: action + narration persisted.
        messages = store.load_messages(session_id)
        assert {"role": "user", "content": "attack the goblin"} in messages
        assert {"role": "assistant", "content": _FOLLOW_UP_NARRATION} in messages

        # Character persisted and reconstructs with recomputed derived values.
        saved_character = store.load_character(session_id)
        assert saved_character is not None
        assert saved_character.name == "Thorn"
        assert saved_character.max_hp == _MAX_HP
    finally:
        store.close()
