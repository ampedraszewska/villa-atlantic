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

3. **Checkout-day rule**: iCal DTEND for all-day events is exclusive, so a
   booking Apr 22 .. Apr 29 inclusive is DTEND:20260430. We shift DTEND
   back by one day so the event only blocks the nights, leaving the
   checkout day free for the next guest to check in. If DTSTART == DTEND
   (a single-day artefact that would collapse to zero duration) we drop
   the event entirely — it represents zero overnight stays.

Use as a library (`from sanitize_ical import sanitize`) or as a CLI:

    python3 scripts/sanitize_ical.py <path-to-raw.ics> [<path-to-output.ics>]

If the output path is omitted the raw file is overwritten in-place.
"""

from __future__ import annotations

import datetime
import pathlib
import re
import sys

KEEP_IN_EVENT = {'DTSTART', 'DTEND', 'UID', 'RRULE', 'EXDATE', 'RECURRENCE-ID'}
STRIP_AT_CAL = {'X-WR-CALDESC', 'X-WR-CALNAME'}

_DATE_PATTERN = re.compile(r'^(DTEND[^:]*:)(\d{8})(T\d{6}Z?)?$')
_FOLDED_LINE = re.compile(r'\r?\n[ \t]')


def unfold(text: str) -> str:
    """Unfold RFC 5545 continuation lines (a line starting with space/tab
    continues the previous one)."""
    return _FOLDED_LINE.sub('', text)


def shift_dtend_back_one_day(line: str) -> str:
    """Return DTEND line with its date shifted back one day. Non-DTEND
    lines and lines without a parseable 8-digit date are returned
    unchanged."""
    m = _DATE_PATTERN.match(line)
    if not m:
        return line
    prefix, date_str, time_part = m.groups()
    d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    new_d = d - datetime.timedelta(days=1)
    return prefix + new_d.strftime('%Y%m%d') + (time_part or '')


def sanitize(src: str) -> str:
    """Sanitize raw Google iCal text and return the public-safe version.

    Pure function, deterministic, no I/O. Safe to call repeatedly
    (idempotent on already-sanitized input)."""
    src = unfold(src).replace('\r\n', '\n')
    out: list[str] = []
    in_event = False
    ev: list[str] = []
    for line in src.split('\n'):
        if line == 'BEGIN:VEVENT':
            in_event, ev = True, []
            continue
        if line == 'END:VEVENT':
            dtstart = next((l for l in ev if l.startswith('DTSTART')), None)
            dtend = next((l for l in ev if l.startswith('DTEND')), None)
            if dtstart and dtend:
                dtstart_date = re.search(r'(\d{8})', dtstart)
                dtend_date = re.search(r'(\d{8})', dtend)
                if (dtstart_date and dtend_date
                        and dtstart_date.group(1) == dtend_date.group(1)):
                    # Zero-duration event (Google's single-day artefact) —
                    # represents no actual overnight stay, skip.
                    in_event = False
                    continue
            out.append('BEGIN:VEVENT')
            out.extend(shift_dtend_back_one_day(l) for l in ev)
            out.append('SUMMARY:Booked')
            out.append('TRANSP:OPAQUE')
            out.append('END:VEVENT')
            in_event = False
            continue
        key = line.split(':', 1)[0].split(';', 1)[0]
        if in_event:
            if key in KEEP_IN_EVENT:
                ev.append(line)
        else:
            if key in STRIP_AT_CAL:
                continue
            # DTSTAMP at calendar level changes every fetch and would cause
            # spurious commits — drop it so we only commit real data changes.
            if key == 'DTSTAMP':
                continue
            # Skip blank lines so repeated sanitize passes don't keep
            # adding a trailing \r\n to the output.
            if line == '':
                continue
            out.append(line)
    return '\r\n'.join(out) + '\r\n'


def _main(argv: list[str]) -> int:
    if len(argv) < 2 or len(argv) > 3:
        print(
            f'usage: {argv[0]} <input.ics> [<output.ics>]',
            file=sys.stderr,
        )
        return 2
    in_path = pathlib.Path(argv[1])
    out_path = pathlib.Path(argv[2]) if len(argv) == 3 else in_path
    out_path.write_text(
        sanitize(in_path.read_text(encoding='utf-8')),
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv))
