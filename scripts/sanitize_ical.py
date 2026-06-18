"""
Villa Atlantic iCal sanitizer.

Transforms Google Calendar's public iCal feed into a version safe to serve
publicly from the villa website.

Three jobs:

1. **Privacy**: keep only the minimum properties needed for FullCalendar to
   render a block (DTSTART, DTEND, UID, RRULE, EXDATE, RECURRENCE-ID). Drop
   SUMMARY, DESCRIPTION, LOCATION, ATTENDEE, ORGANIZER, anything else —
   then overwrite SUMMARY with the literal "Booked" so no guest detail
   ever reaches the public ICS file.

2. **Correctness**: force every event to TRANSP:OPAQUE so an event marked
   "Free" in Google Calendar still blocks the date on the site. Parents
   shouldn't have to remember the availability dropdown.

3. **Checkout-day rule**: if a booking ends Apr 29 (guest leaves that
   morning), Apr 29 should stay AVAILABLE because the next guest can check
   in that same day. The shift only applies to date-only all-day events.
   Timed events already encode a precise checkout moment and shifting them
   would corrupt duration. If the all-day shift collapses an event to zero
   duration, we drop the event entirely.

Use as a library (`from sanitize_ical import sanitize`) or as a CLI:

    python3 scripts/sanitize_ical.py <path-to-raw.ics> [<path-to-output.ics>]

If the output path is omitted the raw file is overwritten in-place.
"""

from __future__ import annotations

import datetime
import pathlib
import re
import sys

KEEP_IN_EVENT = {"DTSTART", "DTEND", "UID", "RRULE", "EXDATE", "RECURRENCE-ID"}
STRIP_AT_CAL = {"X-WR-CALDESC", "X-WR-CALNAME"}

_DATE_ONLY_DTEND = re.compile(r"^(DTEND[^:]*:)(\d{8})$")
_DATE_ONLY_FIELD = re.compile(r"^(?:DTSTART|DTEND)[^:]*:(\d{8})$")
_FOLDED_LINE = re.compile(r"\r?\n[ \t]")


def unfold(text: str) -> str:
    """Unfold RFC 5545 continuation lines (a line starting with space/tab
    continues the previous one)."""
    return _FOLDED_LINE.sub("", text)


def parse_date_only(line: str) -> datetime.date | None:
    """Parse a date-only DTSTART/DTEND content line."""
    m = _DATE_ONLY_FIELD.match(line)
    if not m:
        return None
    date_str = m.group(1)
    return datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))


def shift_dtend_back_one_day(line: str) -> str:
    """Shift a date-only DTEND line back one day."""
    m = _DATE_ONLY_DTEND.match(line)
    if not m:
        return line
    prefix, date_str = m.groups()
    d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    new_d = d - datetime.timedelta(days=1)
    return prefix + new_d.strftime("%Y%m%d")


def sanitize(src: str) -> str:
    """Sanitize raw Google iCal text and return the public-safe version.

    Pure function, deterministic, no I/O."""
    src = unfold(src).replace("\r\n", "\n")
    out: list[str] = []
    in_event = False
    ev: list[str] = []
    for line in src.split("\n"):
        if line == "BEGIN:VEVENT":
            in_event, ev = True, []
            continue
        if line == "END:VEVENT":
            shifted_ev = [shift_dtend_back_one_day(ln) for ln in ev]
            dtstart = next((ln for ln in shifted_ev if ln.startswith("DTSTART")), None)
            dtend = next((ln for ln in shifted_ev if ln.startswith("DTEND")), None)
            if dtstart and dtend:
                dtstart_date = parse_date_only(dtstart)
                dtend_date = parse_date_only(dtend)
                if dtstart_date and dtend_date and dtend_date <= dtstart_date:
                    # The checkout-day shift collapsed this all-day event.
                    # It represents no actual overnight stay, so skip it.
                    in_event = False
                    continue
            out.append("BEGIN:VEVENT")
            out.extend(shifted_ev)
            out.append("SUMMARY:Booked")
            out.append("TRANSP:OPAQUE")
            out.append("END:VEVENT")
            in_event = False
            continue
        key = line.split(":", 1)[0].split(";", 1)[0]
        if in_event:
            if key in KEEP_IN_EVENT:
                ev.append(line)
        else:
            if key in STRIP_AT_CAL:
                continue
            # DTSTAMP at calendar level changes every fetch and would cause
            # spurious commits — drop it so we only commit real data changes.
            if key == "DTSTAMP":
                continue
            # Skip blank lines so repeated sanitize passes don't keep
            # adding a trailing \r\n to the output.
            if line == "":
                continue
            out.append(line)
    return "\r\n".join(out) + "\r\n"


def _normalize_date(value: str) -> str:
    """Date-only iCal value (YYYYMMDD) -> YYYY-MM-DD; otherwise returned as-is."""
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def parse_events(text: str) -> dict[str, dict[str, str | None]]:
    """Parse VEVENTs from iCal text into ``{uid: {start, end, created,
    last_modified}}``.

    Dates are normalized to ``YYYY-MM-DD`` for date-only values (timed values
    kept raw). ``created``/``last_modified`` come from the raw feed's CREATED /
    LAST-MODIFIED (absent in the sanitized feed, which strips them) and are
    ``None`` when missing. Events without a UID are skipped — they can't be
    diffed or restored. Shared by sync_guard (event counting) and
    log_ical_changes (UID diffing)."""
    text = unfold(text).replace("\r\n", "\n")
    events: dict[str, dict[str, str | None]] = {}
    in_event = False
    cur: dict[str, str | None] = {}
    for line in text.split("\n"):
        if line == "BEGIN:VEVENT":
            in_event, cur = (
                True,
                {"start": None, "end": None, "created": None, "last_modified": None},
            )
            continue
        if line == "END:VEVENT":
            uid = cur.pop("uid", None)
            if in_event and uid:
                events[uid] = cur
            in_event = False
            continue
        if not in_event or ":" not in line:
            continue
        key = line.split(":", 1)[0].split(";", 1)[0]
        value = line.split(":", 1)[1]
        if key == "UID":
            cur["uid"] = value
        elif key == "DTSTART":
            cur["start"] = _normalize_date(value)
        elif key == "DTEND":
            cur["end"] = _normalize_date(value)
        elif key == "CREATED":
            cur["created"] = value
        elif key == "LAST-MODIFIED":
            cur["last_modified"] = value
    return events


def _main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) > 3:
        print(
            f"usage: {argv[0]} <input.ics> [<output.ics>]",
            file=sys.stderr,
        )
        return 2
    in_path = pathlib.Path(argv[1])
    out_path = pathlib.Path(argv[2]) if len(argv) == 3 else in_path
    out_path.write_text(
        sanitize(in_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
