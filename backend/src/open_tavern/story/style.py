"""DM narration-style model and preset registry.

Tone and verbosity are preset *keys* resolved server-side into prompt
instruction lines, so prompt wording stays reviewable and testable. The custom
note is the open-ended escape hatch; it is sanitized at prompt-build time
(see ``prompts._sanitize_gm``) because style lines render as GM instructions,
not fenced untrusted data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DmStyle:
    """How the AI DM speaks: preset tone, preset verbosity, a free-form note."""

    tone: str
    verbosity: str
    custom_tone: str = ""


DEFAULT_TONE = "classic"
DEFAULT_VERBOSITY = "standard"
DEFAULT_STYLE = DmStyle(tone=DEFAULT_TONE, verbosity=DEFAULT_VERBOSITY)

#: Preset tone key -> GM instruction line. ``classic`` renders no line.
TONES: dict[str, str] = {
    "classic": "",
    "gritty": (
        "Narrate with a gritty, dangerous edge: the world is unforgiving, "
        "and wounds and costs matter."
    ),
    "heroic": (
        "Narrate with a heroic, epic sweep: bold stakes, valiant deeds, "
        "cinematic action."
    ),
    "whimsical": "Narrate with whimsical charm: playful details, light humor, wonder.",
    "comedic": (
        "Narrate for laughs: comedic timing and absurd flourishes, "
        "but keep the game mechanics intact."
    ),
}

#: Preset verbosity key -> GM instruction line. ``standard`` renders no line.
VERBOSITIES: dict[str, str] = {
    "standard": "",
    "concise": "Keep narration tight: at most two short paragraphs per response.",
    "rich": (
        "Write immersive narration of three to five paragraphs "
        "with vivid sensory detail."
    ),
}


def normalize_dm_style(data: DmStyle | dict | None) -> DmStyle:
    """Coerce *data* to a validated :class:`DmStyle`.

    Accepts a :class:`DmStyle`, a raw dict (e.g. decoded from JSON storage), or
    ``None``. Unknown preset keys and unknown dict fields fall back to
    defaults, so a legacy or hand-edited row always yields a usable style.
    """
    if isinstance(data, DmStyle):
        raw: dict = {
            "tone": data.tone,
            "verbosity": data.verbosity,
            "custom_tone": data.custom_tone,
        }
    elif isinstance(data, dict):
        raw = data
    else:
        raw = {}
    tone = raw.get("tone")
    verbosity = raw.get("verbosity")
    custom_tone = raw.get("custom_tone")
    return DmStyle(
        tone=tone if isinstance(tone, str) and tone in TONES else DEFAULT_TONE,
        verbosity=(
            verbosity
            if isinstance(verbosity, str) and verbosity in VERBOSITIES
            else DEFAULT_VERBOSITY
        ),
        custom_tone=custom_tone if isinstance(custom_tone, str) else "",
    )
