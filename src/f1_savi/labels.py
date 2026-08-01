from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]*>")
_WHITESPACE = re.compile(r"\s+")


def normalise_display_label(value: object) -> str:
    """Convert FantasyGP display-name HTML into stable plain text."""
    text = html.unescape(str(value))
    text = _TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()
