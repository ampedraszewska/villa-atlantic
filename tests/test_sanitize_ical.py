"""Tests for scripts/sanitize_ical.py.

Each test maps to a specific regression that was observed in production or
is plausible enough to be worth a permanent fence. Fixture files live in
tests/fixtures/ical/ and represent the raw output style Google Calendar
produces for our public feed.
"""
import pathlib
import re
import subprocess
import sys

import pytest
from icalendar import Calendar

from sanitize_ical import KEEP_IN_EVENT, sanitize, shift_dtend_back_one_day

FIXTURES = pathlib.Path(__file__).parent / 'fixtures' / 'ical'
SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / 'scripts'
    / 'sanitize_ical.py'
)


def _load(name: str) -> str:
    return (FIXTURES / f'{name}.ics').read_text(encoding='utf-8')


def _events(ics: str) -> list:
    """Return list of VEVENT components parsed from iCal text."""
    cal = Calendar.from_ical(ics)
    return [c for c in cal.walk() if c.name == 'VEVENT']


def test_sanitize_output_parses_as_valid_ical():
    """icalendar library round-trips every fixture without raising."""
    for fixture in ['empty', 'busy_event', 'free_event', 'guest_details',
                    'folded_description', 'one_night', 'whole_week',
                    'rrule_event', 'multiple_events', 'timed_event']:
        out = sanitize(_load(fixture))
        Calendar.from_ical(out)  # would raise on malformed iCal


def test_empty_calendar_preserved():
    out = sanitize(_load('empty'))
    assert 'BEGIN:VCALENDAR' in out
    assert 'END:VCALENDAR' in out
    assert 'BEGIN:VEVENT' not in out


def test_summary_always_replaced_with_booked():
    for fixture in ['busy_event', 'free_event', 'guest_details',
                    'folded_description', 'rrule_event']:
        out = sanitize(_load(fixture))
        for ev in _events(out):
            assert str(ev['SUMMARY']) == 'Booked', (
                f'{fixture}: summary leaked — got {ev["SUMMARY"]!r}'
            )


def test_transp_always_opaque_even_for_transparent_source():
    """The bug that brought us here: Google Calendar lets users mark an
    event as availability=Free (TRANSP:TRANSPARENT), which previously
    caused the event to be filtered out of the public feed entirely.
    Sanitizer must force OPAQUE so any booking blocks the dates."""
    out = sanitize(_load('free_event'))
    for ev in _events(out):
        assert str(ev['TRANSP']) == 'OPAQUE'


def test_dtend_shifted_back_one_day_for_multi_night_booking():
    """Booking Apr 22..29 inclusive is DTEND:20260430 in iCal. After shift
    it must become DTEND:20260429 so Apr 29 (checkout day) remains
    available for the next guest to check in."""
    out = sanitize(_load('whole_week'))
    events = _events(out)
    assert len(events) == 1
    assert events[0]['DTEND'].to_ical() == b'20260429'


def test_one_night_booking_leaves_checkout_day_free():
    """A 1-night stay under our calendar convention includes check-in and
    checkout dates. Google emits DTEND:17, which shifts to DTEND:16 so the
    checkout day remains free."""
    out = sanitize(_load('one_night'))
    events = _events(out)
    assert len(events) == 1
    assert events[0]['DTSTART'].to_ical() == b'20260515'
    assert events[0]['DTEND'].to_ical() == b'20260516'


def test_single_day_event_dropped_entirely():
    """A single selected all-day date collapses after the checkout-day
    shift and represents zero overnight stays — drop it."""
    out = sanitize(_load('single_day'))
    assert 'BEGIN:VEVENT' not in out


def test_timed_event_dtend_not_shifted():
    """Timed events already encode the precise checkout moment. Shifting
    their DTEND would make ordinary overnight timed bookings end before
    they start."""
    out = sanitize(_load('timed_event'))
    events = _events(out)
    assert len(events) == 1
    assert events[0]['DTSTART'].to_ical() == b'20260601T160000'
    assert events[0]['DTEND'].to_ical() == b'20260602T100000'


def test_cli_entrypoint_preserves_checkout_edge_case_contract(tmp_path):
    """The sync workflow invokes the sanitizer as a script, so cover the
    checkout-day contract through that entrypoint too: one-night stays are
    kept, zero-night all-day artefacts are dropped, and timed stays are not
    shifted."""
    raw = tmp_path / 'raw.ics'
    out_path = tmp_path / 'public.ics'
    raw.write_text(
        '\n'.join([
            'BEGIN:VCALENDAR',
            'PRODID:-//Google Inc//Google Calendar 70.9054//EN',
            'VERSION:2.0',
            'BEGIN:VEVENT',
            'DTSTART;VALUE=DATE:20260515',
            'DTEND;VALUE=DATE:20260517',
            'UID:one-night-cli@google.com',
            'SUMMARY:One night stay',
            'END:VEVENT',
            'BEGIN:VEVENT',
            'DTSTART;VALUE=DATE:20260520',
            'DTEND;VALUE=DATE:20260521',
            'UID:zero-night-cli@google.com',
            'SUMMARY:Zero-night artefact',
            'END:VEVENT',
            'BEGIN:VEVENT',
            'DTSTART;TZID=Atlantic/Canary:20260601T160000',
            'DTEND;TZID=Atlantic/Canary:20260602T100000',
            'UID:timed-cli@google.com',
            'SUMMARY:Timed stay',
            'END:VEVENT',
            'END:VCALENDAR',
            '',
        ]),
        encoding='utf-8',
    )

    subprocess.run(
        [sys.executable, str(SCRIPT), str(raw), str(out_path)],
        check=True,
    )

    events = {
        str(event['UID']): event
        for event in _events(out_path.read_text(encoding='utf-8'))
    }
    assert set(events) == {'one-night-cli@google.com', 'timed-cli@google.com'}
    assert (
        events['one-night-cli@google.com']['DTSTART'].to_ical()
        == b'20260515'
    )
    assert (
        events['one-night-cli@google.com']['DTEND'].to_ical()
        == b'20260516'
    )
    assert (
        events['timed-cli@google.com']['DTSTART'].to_ical()
        == b'20260601T160000'
    )
    assert (
        events['timed-cli@google.com']['DTEND'].to_ical()
        == b'20260602T100000'
    )


def test_guest_pii_stripped_from_output():
    """Sanitizer must never leak any guest identifier into the public
    feed. The guest_details.ics fixture has name, email, phone,
    description, location, attendee, organizer — none should appear."""
    out = sanitize(_load('guest_details'))
    forbidden = [
        'Kowalski', 'Jan', 'jan.kowalski', '+48 501',
        'Aleksandra', 'a.pedraszewska',
        'Dwójka dzieci', 'łóżeczka',
        'apartament dolny',
        'example.com/booking',
    ]
    for needle in forbidden:
        assert needle not in out, f'PII leaked: {needle!r} in output'


def test_folded_multiline_description_fully_stripped():
    """RFC 5545 line folding: long properties are wrapped with leading
    space/tab on continuation lines. Sanitizer must unfold first so the
    continuation lines aren't orphaned and the full DESCRIPTION is
    treated as one property and stripped."""
    out = sanitize(_load('folded_description'))
    forbidden = ['Anna', 'Nowak', 'anna.nowak', '+48 600',
                 'labrador', 'Goście proszą', 'wczesny check-in']
    for needle in forbidden:
        assert needle not in out, f'folded content leaked: {needle!r}'


def test_x_wr_caldesc_stripped_at_calendar_level():
    """Calendar-level description can contain operator notes; strip it
    from the public feed."""
    # empty.ics has X-WR-CALDESC; multiple_events.ics has it too.
    for fixture in ['empty', 'multiple_events', 'folded_description']:
        out = sanitize(_load(fixture))
        assert 'X-WR-CALDESC' not in out


def test_x_wr_calname_stripped():
    for fixture in ['empty', 'busy_event', 'free_event', 'multiple_events']:
        out = sanitize(_load(fixture))
        assert 'X-WR-CALNAME' not in out


def test_dtstamp_stripped_from_output():
    """DTSTAMP changes on every fetch and would produce noisy diffs in
    the ical/*.ics files committed by the sync workflow. Drop it."""
    for fixture in ['busy_event', 'free_event', 'guest_details']:
        out = sanitize(_load(fixture))
        assert 'DTSTAMP' not in out


def test_whitelisted_properties_only_in_events():
    """Any property inside VEVENT that isn't in KEEP_IN_EVENT must be
    absent (except the SUMMARY/TRANSP we inject)."""
    out = sanitize(_load('guest_details'))
    for ev in _events(out):
        for key in ev.keys():
            if key in {'SUMMARY', 'TRANSP'}:
                continue  # injected by sanitizer
            assert key in KEEP_IN_EVENT, (
                f'non-whitelisted property in VEVENT: {key}'
            )


def test_rrule_and_exdate_preserved():
    """Recurring 'villa closed' rules must round-trip through sanitize."""
    out = sanitize(_load('rrule_event'))
    events = _events(out)
    assert len(events) == 1
    assert 'RRULE' in events[0]
    assert 'EXDATE' in events[0]


def test_multiple_events_sanitized_and_single_day_dropped():
    out = sanitize(_load('multiple_events'))
    events = _events(out)
    # Fixture has 3 VEVENTs; the third collapses after checkout-day shift
    # and must be dropped.
    assert len(events) == 2
    uids = {str(e['UID']) for e in events}
    assert 'multi-a@google.com' in uids
    assert 'multi-b@google.com' in uids
    assert 'multi-c-skip@google.com' not in uids


def test_blank_lines_do_not_accumulate():
    """Running sanitize on an empty-calendar input and then on its own
    output must not keep appending trailing blank lines — otherwise
    every re-run grows the file."""
    once = sanitize(_load('empty'))
    twice = sanitize(once)
    # Output length should stabilise; allow a single trailing CRLF.
    assert len(twice) <= len(once) + 2


def test_sanitize_is_semantically_non_idempotent_for_dtend_shift():
    """Explicit contract: sanitize applies a one-day DTEND shift each
    time it runs. The sync workflow always feeds freshly-fetched raw
    Google iCal, so this is safe. Re-running on already-shifted output
    would double-shift — this test pins that behaviour so anyone
    refactoring the sanitizer has to consciously decide whether to
    change it."""
    once = sanitize(_load('whole_week'))
    twice = sanitize(once)
    dtend_once = _events(once)[0]['DTEND'].to_ical()
    dtend_twice = _events(twice)[0]['DTEND'].to_ical()
    # Expect the second pass to shift DTEND back one more day.
    assert dtend_once == b'20260429'
    assert dtend_twice == b'20260428'


def test_output_uses_crlf_line_endings():
    """RFC 5545 requires CRLF between content lines. Several strict
    consumers (some Outlook versions, older .ics parsers) reject LF-only
    feeds. Browsers and FullCalendar are lenient but we should emit a
    compliant format."""
    out = sanitize(_load('busy_event'))
    # Every line ending that's not the tail should be \r\n
    assert out.endswith('\r\n')
    assert '\r\n' in out
    # No bare \n (other than inside the final \r\n)
    bare_lf = re.findall(r'(?<!\r)\n', out)
    assert not bare_lf, 'found LF without preceding CR'


def test_shift_dtend_standalone_helper():
    """Direct unit test of the shift helper — catches off-by-one or
    regex regressions independently of the sanitize() pipeline."""
    assert (
        shift_dtend_back_one_day('DTEND;VALUE=DATE:20260430')
        == 'DTEND;VALUE=DATE:20260429'
    )
    assert (
        shift_dtend_back_one_day('DTEND:20260301')
        == 'DTEND:20260228'
    )  # Feb/March boundary, non-leap year
    assert (
        shift_dtend_back_one_day('DTEND:20240301')
        == 'DTEND:20240229'
    )  # leap year
    # Timed DTEND lines are precise checkout moments; leave them untouched.
    assert (
        shift_dtend_back_one_day('DTEND;TZID=Atlantic/Canary:20260602T100000')
        == 'DTEND;TZID=Atlantic/Canary:20260602T100000'
    )
    assert (
        shift_dtend_back_one_day('DTEND:20260602T100000Z')
        == 'DTEND:20260602T100000Z'
    )
    # Non-DTEND lines untouched
    assert (
        shift_dtend_back_one_day('DTSTART;VALUE=DATE:20260430')
        == 'DTSTART;VALUE=DATE:20260430'
    )


@pytest.mark.parametrize('fixture', [
    'empty', 'busy_event', 'free_event', 'guest_details',
    'folded_description', 'one_night', 'whole_week',
    'rrule_event', 'multiple_events', 'timed_event',
])
def test_no_literal_transparent_in_output(fixture):
    """Belt-and-braces companion to test_transp_always_opaque."""
    out = sanitize(_load(fixture))
    assert 'TRANSPARENT' not in out
