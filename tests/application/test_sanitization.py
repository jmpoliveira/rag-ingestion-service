from __future__ import annotations

import pytest

from src.application.sanitization import clean_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("plain", "plain"),
        ("zero\u200bwidth", "zerowidth"),
        ("bidi \u202eoverride", "bidi override"),
        ("control\x07char", "controlchar"),
        ("many    spaces\tand\u00a0nbsp", "many spaces and nbsp"),
        ("windows\r\nlines\rmac", "windows\nlines\nmac"),
        ("para one\n\n\n\n\npara two", "para one\n\npara two"),
        ("  trailing  \n  leading", "trailing\nleading"),
        ("cafe\u0301", "café"),  # NFC: decomposed accent becomes one character
    ],
)
def test_clean_text(raw: str, expected: str):
    assert clean_text(raw) == expected


def test_clean_text_is_idempotent():
    # Arrange
    once = clean_text("a\u200b  b\n\n\n\nc ")

    # Act / Assert
    assert clean_text(once) == once
