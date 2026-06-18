"""Tests for scripts/sync_guard.py — the accidental-wipe guard.

The guard must trip on exactly one pattern: a feed that held >= 2 bookings
suddenly returning 0. Everything else publishes normally.
"""

import pytest
from sync_guard import is_wipe


def _feed(n: int) -> str:
    """An iCal feed carrying n distinct all-day events."""
    events = "".join(
        f"BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:2026010{i}\r\n"
        f"DTEND;VALUE=DATE:2026010{i + 1}\r\nUID:e{i}@google.com\r\nEND:VEVENT\r\n"
        for i in range(1, n + 1)
    )
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{events}END:VCALENDAR\r\n"


@pytest.mark.parametrize(
    "before_n,after_n,expected",
    [
        (2, 0, True),  # full wipe of a busy calendar — the dangerous case
        (3, 0, True),
        (1, 0, False),  # a lone booking checking out is normal
        (2, 1, False),  # partial change is normal
        (0, 0, False),  # already empty stays empty
        (0, 2, False),  # fresh bookings appearing is normal
        (5, 5, False),  # unchanged
    ],
)
def test_is_wipe(before_n, after_n, expected):
    assert is_wipe(_feed(before_n), _feed(after_n)) is expected


def test_missing_before_is_not_a_wipe():
    """Empty/absent before state must never be read as a wipe."""
    assert is_wipe("", _feed(0)) is False
    assert is_wipe("", _feed(3)) is False
