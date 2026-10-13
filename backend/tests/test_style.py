"""Tests for the DM narration-style model and preset registry."""

from __future__ import annotations

from open_tavern.story.style import (
    DEFAULT_TONE,
    DEFAULT_VERBOSITY,
    TONES,
    VERBOSITIES,
    DmStyle,
    normalize_dm_style,
)


def test_preset_registry_has_instruction_lines_except_defaults():
    assert TONES[DEFAULT_TONE] == ""
    assert VERBOSITIES[DEFAULT_VERBOSITY] == ""
    for key, line in TONES.items():
        if key != DEFAULT_TONE:
            assert line.strip(), f"tone {key!r} must map to an instruction line"
    for key, line in VERBOSITIES.items():
        if key != DEFAULT_VERBOSITY:
            assert line.strip(), f"verbosity {key!r} must map to an instruction line"


def test_normalize_none_and_empty_dict_give_defaults():
    default = DmStyle(DEFAULT_TONE, DEFAULT_VERBOSITY)
    assert normalize_dm_style(None) == default
    assert normalize_dm_style({}) == default


def test_normalize_fills_missing_fields_from_defaults():
    assert normalize_dm_style({"tone": "gritty"}) == DmStyle(
        "gritty", DEFAULT_VERBOSITY
    )
    assert normalize_dm_style({"verbosity": "rich"}) == DmStyle(DEFAULT_TONE, "rich")


def test_normalize_falls_back_on_unknown_keys():
    assert normalize_dm_style(
        {"tone": "nope", "verbosity": "purple", "extra": 1}
    ) == DmStyle(DEFAULT_TONE, DEFAULT_VERBOSITY)
    assert normalize_dm_style(DmStyle("nope", "purple")) == DmStyle(
        DEFAULT_TONE, DEFAULT_VERBOSITY
    )


def test_normalize_passes_valid_style_through():
    style = DmStyle("heroic", "rich", "pirate slang")
    assert normalize_dm_style(style) == style
    assert (
        normalize_dm_style(
            {"tone": "heroic", "verbosity": "rich", "custom_tone": "pirate slang"}
        )
        == style
    )


def test_normalize_coerces_bad_custom_note_to_empty():
    assert normalize_dm_style({"custom_tone": None}).custom_tone == ""
    assert normalize_dm_style({"custom_tone": 5}).custom_tone == ""
