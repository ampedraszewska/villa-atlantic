"""Tests for scripts/restore_booking.py — booking recovery from the ledger."""

import json

import pytest
from icalendar import Calendar
from restore_booking import (
    _report,
    build_vevent,
    insert_event,
    load_ledger,
    reconstruct,
)
from sanitize_ical import parse_events


def _write_ledger(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _rec(action, apt, uid, start, end, detected_at, **extra):
    return {
        "detected_at": detected_at,
        "apartment": apt,
        "action": action,
        "uid": uid,
        "start": start,
        "end": end,
        **extra,
    }


def test_reconstruct_marks_removed_and_present(tmp_path):
    log = tmp_path / "changelog.jsonl"
    _write_ledger(
        log,
        [
            _rec(
                "added",
                "cliffs",
                "a@g",
                "2026-07-13",
                "2026-07-22",
                "2026-04-01T00:00:00Z",
                created="20260401T000000Z",
            ),
            _rec(
                "added",
                "cliffs",
                "b@g",
                "2026-09-18",
                "2026-10-02",
                "2026-04-01T00:00:00Z",
                created="20260401T000000Z",
            ),
            _rec("removed", "cliffs", "a@g", "2026-07-13", "2026-07-22", "2026-06-14T10:00:00Z"),
        ],
    )
    state = reconstruct(load_ledger(log))
    assert state["cliffs"]["a@g"]["status"] == "removed"
    assert state["cliffs"]["a@g"]["removed_at"] == "2026-06-14T10:00:00Z"
    assert state["cliffs"]["b@g"]["status"] == "present"


def test_readded_booking_is_present_again(tmp_path):
    log = tmp_path / "changelog.jsonl"
    _write_ledger(
        log,
        [
            _rec("added", "cliffs", "a@g", "2026-07-13", "2026-07-22", "2026-04-01T00:00:00Z"),
            _rec("removed", "cliffs", "a@g", "2026-07-13", "2026-07-22", "2026-06-14T10:00:00Z"),
            _rec("added", "cliffs", "a@g", "2026-07-13", "2026-07-22", "2026-06-15T10:00:00Z"),
        ],
    )
    state = reconstruct(load_ledger(log))
    assert state["cliffs"]["a@g"]["status"] == "present"


def test_report_lists_recovery_candidates(tmp_path):
    log = tmp_path / "changelog.jsonl"
    _write_ledger(
        log,
        [
            _rec("added", "cliffs", "a@g", "2026-07-13", "2026-07-22", "2026-04-01T00:00:00Z"),
            _rec("removed", "cliffs", "a@g", "2026-07-13", "2026-07-22", "2026-06-14T10:00:00Z"),
        ],
    )
    out = _report(reconstruct(load_ledger(log)))
    assert "recovery candidates (1)" in out
    assert "2026-07-13 -> 2026-07-22" in out
    assert "a@g" in out


def test_quarantine_records_ignored_by_reconstruct(tmp_path):
    log = tmp_path / "changelog.jsonl"
    _write_ledger(
        log,
        [
            {
                "detected_at": "2026-06-14T10:00:00Z",
                "apartment": "cliffs",
                "action": "quarantined",
                "before_count": 2,
                "preserved": [{"uid": "a@g", "start": "2026-07-13", "end": "2026-07-22"}],
            },
        ],
    )
    state = reconstruct(load_ledger(log))
    assert state == {}


def test_reinstate_produces_valid_event_with_ledger_dates():
    live = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    vevent = build_vevent("a@g", "2026-07-13", "2026-07-22")
    result = insert_event(live, vevent)
    # parses as valid iCal
    cal = Calendar.from_ical(result)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 1
    # round-trips through our own parser with the ledger's dates intact
    parsed = parse_events(result)
    assert parsed["a@g"]["start"] == "2026-07-13"
    assert parsed["a@g"]["end"] == "2026-07-22"
    assert "SUMMARY:Booked" in result and "TRANSP:OPAQUE" in result


def test_insert_event_refuses_malformed_feed():
    with pytest.raises(ValueError):
        insert_event("not a calendar", build_vevent("a@g", "2026-07-13", "2026-07-22"))


def test_build_vevent_keeps_timed_value_raw():
    """A timed ledger value (parse_events keeps timed values raw) must be
    emitted without the VALUE=DATE parameter — tagging a date-time as
    VALUE=DATE violates RFC 5545 and makes parsers drop the time, turning a
    timed booking into a broken all-day one."""
    vevent = build_vevent("t@g", "20260713T100000Z", "20260715T120000Z")
    assert "DTSTART:20260713T100000Z" in vevent
    assert "DTEND:20260715T120000Z" in vevent
    assert "VALUE=DATE" not in vevent
    # icalendar parses it as a real date-time, and it round-trips raw.
    live = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    result = insert_event(live, vevent)
    Calendar.from_ical(result)  # must not raise
    assert parse_events(result)["t@g"]["start"] == "20260713T100000Z"


def test_build_vevent_date_only_uses_value_date():
    """Date-only ledger values keep the all-day VALUE=DATE form."""
    vevent = build_vevent("d@g", "2026-07-13", "2026-07-22")
    assert "DTSTART;VALUE=DATE:20260713" in vevent
    assert "DTEND;VALUE=DATE:20260722" in vevent
