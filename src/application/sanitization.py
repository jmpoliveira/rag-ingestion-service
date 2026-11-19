"""Text cleaning applied to every page before chunking.

Documents are untrusted input: whatever is indexed today ends up inside an agent's prompt
tomorrow. Cleaning removes characters that hide text from a human reviewer (zero-width,
bidirectional overrides, control characters) and normalises whitespace so the same text
always produces the same chunks. It does **not** remove prompt injection written in plain
words: the consumer (the agent) treats retrieved text as untrusted data and frames it.
"""

from __future__ import annotations

import re
import unicodedata

# Bump when the cleaning changes: it is part of every document version, so documents are
# re-ingested with the new rules on the next sync.
CLEANING_VERSION = 1

# Control (Cc), format (Cf: zero-width, bidi overrides), surrogate (Cs), private-use (Co) and
# unassigned (Cn) characters. Newlines and tabs survive (tabs become spaces below).
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_KEPT = frozenset({"\n", "\t"})
_SPACES = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """NFC-normalise, drop hidden characters and collapse whitespace."""
    normalised = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    visible = "".join(
        ch
        for ch in normalised
        if ch in _KEPT or unicodedata.category(ch) not in _DROPPED_CATEGORIES
    )
    lines = (_SPACES.sub(" ", line).strip() for line in visible.split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
