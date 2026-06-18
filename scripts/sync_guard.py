"""Villa Atlantic sync guard.

Refuses to let an accidental full calendar wipe blank the live site.

A "wipe" is the one dangerous pattern observed in production: a calendar that
held real bookings suddenly returns *zero* events from Google (someone deleted
everything, or the feed broke). Publishing that empties the site and invites
double-bookings.

The guard trips on exactly one condition, per feed:

    previous feed had >= 2 events  AND  new feed has 0 events

Anything else publishes normally: a single checkout (1 -> 0), partial change
(2 -> 1), additions, reorders. The 2+ floor avoids tripping on a calendar that
only ever had one booking.

CLI (used by the sync workflow):

    python3 scripts/sync_guard.py <before.ics> <after.ics>

Exit 0 = safe to publish. Exit 3 = wipe detected, do NOT publish. Exit 2 =
usage error. On a wipe it prints a human-readable summary to stdout (consumed
into the alert email).
"""

from __future__ import annotations

import pathlib
import sys

from sanitize_ical import parse_events

WIPE_EXIT = 3


def is_wipe(before_text: str, after_text: str) -> bool:
    """True iff the before feed had >= 2 events and the after feed has 0."""
    before = parse_events(before_text)
    after = parse_events(after_text)
    return len(before) >= 2 and len(after) == 0


def _main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <before.ics> <after.ics>", file=sys.stderr)
        return 2
    before_path, after_path = pathlib.Path(argv[1]), pathlib.Path(argv[2])
    before_text = before_path.read_text(encoding="utf-8") if before_path.exists() else ""
    after_text = after_path.read_text(encoding="utf-8") if after_path.exists() else ""
    before = parse_events(before_text)
    after = parse_events(after_text)
    if len(before) >= 2 and len(after) == 0:
        print(f"WIPE: feed went from {len(before)} events to 0.")
        for uid, ev in sorted(before.items(), key=lambda kv: (kv[1]["start"] or "", kv[0])):
            print(f"  vanished: {ev['start']} -> {ev['end']}  (uid {uid})")
        return WIPE_EXIT
    print(f"OK: {len(before)} -> {len(after)} events.")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
