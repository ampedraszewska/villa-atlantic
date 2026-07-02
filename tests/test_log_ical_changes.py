"""Tests for scripts/log_ical_changes.py — the change ledger."""

import json
import pathlib
import subprocess
import sys

from log_ical_changes import diff_events, pii_clear_record, pii_record, quarantine_record

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "log_ical_changes.py"


def _sanitized(uid: str, start: str, end: str) -> str:
    return (
        f"BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{start}\r\n"
        f"DTEND;VALUE=DATE:{end}\r\nUID:{uid}\r\nSUMMARY:Booked\r\nTRANSP:OPAQUE\r\nEND:VEVENT\r\n"
    )


def _raw(uid: str, start: str, end: str, created: str, modified: str) -> str:
    return (
        f"BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{start}\r\nDTEND;VALUE=DATE:{end}\r\n"
        f"UID:{uid}\r\nCREATED:{created}\r\nLAST-MODIFIED:{modified}\r\nEND:VEVENT\r\n"
    )


def _cal(body: str) -> str:
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{body}END:VCALENDAR\r\n"


def test_added_record_carries_google_timestamps():
    after = _cal(_sanitized("a@g", "20260713", "20260722"))
    raw = _cal(_raw("a@g", "20260713", "20260723", "20260616T163332Z", "20260616T163332Z"))
    recs = diff_events("", after, raw)
    assert len(recs) == 1
    r = recs[0]
    assert r["action"] == "added"
    assert (r["start"], r["end"]) == ("2026-07-13", "2026-07-22")
    assert r["created"] == "20260616T163332Z"
    assert r["last_modified"] == "20260616T163332Z"


def test_removed_record_keeps_last_known_dates():
    before = _cal(_sanitized("a@g", "20260713", "20260722"))
    recs = diff_events(before, _cal(""), _cal(""))
    assert len(recs) == 1
    r = recs[0]
    assert r["action"] == "removed"
    assert (r["start"], r["end"]) == ("2026-07-13", "2026-07-22")
    # created/last_modified are unknowable once the event is gone from the raw feed
    assert r["created"] is None and r["last_modified"] is None


def test_modified_record_has_prev_and_new():
    before = _cal(_sanitized("a@g", "20260713", "20260722"))
    after = _cal(_sanitized("a@g", "20260713", "20260725"))
    raw = _cal(_raw("a@g", "20260713", "20260726", "20260601T000000Z", "20260617T120000Z"))
    recs = diff_events(before, after, raw)
    assert len(recs) == 1
    r = recs[0]
    assert r["action"] == "modified"
    assert (r["prev_start"], r["prev_end"]) == ("2026-07-13", "2026-07-22")
    assert (r["start"], r["end"]) == ("2026-07-13", "2026-07-25")
    assert r["last_modified"] == "20260617T120000Z"


def _timed(uid: str, start: str, end: str, tzid: str) -> str:
    return (
        f"BEGIN:VEVENT\r\nDTSTART;TZID={tzid}:{start}\r\n"
        f"DTEND;TZID={tzid}:{end}\r\nUID:{uid}\r\nSUMMARY:Booked\r\nTRANSP:OPAQUE\r\nEND:VEVENT\r\n"
    )


def test_timezone_only_change_is_recorded():
    """A timed booking re-zoned without moving its wall clock has identical
    start/end strings; the move must still be diffed (via the TZID) so the
    ledger doesn't keep the stale zone."""
    before = _cal(_timed("z@g", "20260713T100000", "20260713T120000", "Europe/Warsaw"))
    after = _cal(_timed("z@g", "20260713T100000", "20260713T120000", "Atlantic/Canary"))
    recs = diff_events(before, after, after)
    assert len(recs) == 1
    r = recs[0]
    assert r["action"] == "modified"
    assert r["start_tzid"] == "Atlantic/Canary"


def test_no_change_yields_no_records():
    feed = _cal(_sanitized("a@g", "20260713", "20260722"))
    assert diff_events(feed, feed, feed) == []


def test_quarantine_record_preserves_all_bookings():
    before = _cal(
        _sanitized("a@g", "20260713", "20260722") + _sanitized("b@g", "20260901", "20260910")
    )
    rec = quarantine_record(before)
    assert rec["action"] == "quarantined"
    assert rec["before_count"] == 2
    uids = {p["uid"] for p in rec["preserved"]}
    assert uids == {"a@g", "b@g"}


def test_cli_appends_jsonl(tmp_path):
    script = SCRIPT
    before = tmp_path / "before.ics"
    after = tmp_path / "after.ics"
    raw = tmp_path / "raw.ics"
    log = tmp_path / "changelog.jsonl"
    before.write_text("", encoding="utf-8")
    after.write_text(_cal(_sanitized("a@g", "20260713", "20260722")), encoding="utf-8")
    raw.write_text(
        _cal(_raw("a@g", "20260713", "20260723", "20260616T163332Z", "20260616T163332Z")),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(script),
            "--apt",
            "cliffs",
            "--before",
            str(before),
            "--after",
            str(after),
            "--raw",
            str(raw),
            "--changelog",
            str(log),
            "--run-url",
            "http://run/1",
            "--sha",
            "abc123",
            "--detected-at",
            "2026-06-18T17:17:04Z",
        ],
        check=True,
    )
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["apartment"] == "cliffs"
    assert entry["detected_at"] == "2026-06-18T17:17:04Z"
    assert entry["action"] == "added"
    assert entry["run_url"] == "http://run/1"
    assert entry["sha_before"] == "abc123"


def test_pii_record_carries_no_event_data():
    """The PII flag must never carry names/dates/UIDs — the raw feed that
    triggered it holds the guest surnames, and the ledger is public."""
    rec = pii_record()
    assert rec == {"action": "pii_detected"}


def test_pii_clear_record_carries_no_event_data():
    rec = pii_clear_record()
    assert rec == {"action": "pii_cleared"}


def _run_pii(log, run_n):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--apt",
            "cliffs",
            "--pii",
            "--changelog",
            str(log),
            "--run-url",
            f"http://run/{run_n}",
            "--sha",
            f"sha{run_n}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run_pii_clear(log, run_n):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--apt",
            "cliffs",
            "--pii-clear",
            "--changelog",
            str(log),
            "--run-url",
            f"http://run/{run_n}",
            "--sha",
            f"sha{run_n}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_pii_is_idempotent_across_runs(tmp_path):
    """While the sharing misconfiguration persists, every hourly run re-detects
    the leak. It must alert once ('recorded') then stay quiet ('already'),
    writing exactly one public-ledger record — no name ever reaches the file."""
    log = tmp_path / "changelog.jsonl"
    assert _run_pii(log, 1) == "recorded"
    assert _run_pii(log, 2) == "already"
    assert _run_pii(log, 3) == "already"
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "pii_detected"
    assert entry["apartment"] == "cliffs"
    # No guest data of any kind in the committed record.
    assert set(entry) == {"action", "apartment", "detected_at", "run_url", "sha_before"}


def test_pii_clear_rearms_later_detection(tmp_path):
    log = tmp_path / "changelog.jsonl"
    assert _run_pii(log, 1) == "recorded"
    assert _run_pii_clear(log, 2) == "cleared"
    assert _run_pii_clear(log, 3) == "clear"
    assert _run_pii(log, 4) == "recorded"

    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [entry["action"] for entry in lines] == [
        "pii_detected",
        "pii_cleared",
        "pii_detected",
    ]


def test_pii_re_records_after_intervening_change(tmp_path):
    """A booking diff logged after the leak clears the 'last record is
    pii_detected' guard, so a later regression re-alerts — the leak is live
    again and the owner needs to know."""
    log = tmp_path / "changelog.jsonl"
    assert _run_pii(log, 1) == "recorded"
    # A normal diff record lands (a booking appeared while / after the leak).
    after = tmp_path / "a.ics"
    after.write_text(_cal(_sanitized("a@g", "20260713", "20260722")), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--apt",
            "cliffs",
            "--after",
            str(after),
            "--changelog",
            str(log),
        ],
        check=True,
    )
    assert _run_pii(log, 2) == "recorded"


def _run_quarantine(before, log, run_n):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--apt",
            "cliffs",
            "--quarantined",
            "--before",
            str(before),
            "--changelog",
            str(log),
            "--run-url",
            f"http://run/{run_n}",
            "--sha",
            f"sha{run_n}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_quarantine_is_idempotent_across_runs(tmp_path):
    """A persisting wipe keeps the last-good feed unchanged, so the before-state
    is identical every hour. The quarantine must be logged once (printing
    'recorded'), then skipped (printing 'duplicate') — otherwise every hourly
    run re-commits a redundant record to the public ledger and re-fires the
    alert."""
    before = tmp_path / "before.ics"
    log = tmp_path / "changelog.jsonl"
    before.write_text(
        _cal(_sanitized("a@g", "20260713", "20260722") + _sanitized("b@g", "20260901", "20260910")),
        encoding="utf-8",
    )
    assert _run_quarantine(before, log, 1) == "recorded"
    assert _run_quarantine(before, log, 2) == "duplicate"
    assert _run_quarantine(before, log, 3) == "duplicate"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_quarantine_re_records_when_wipe_changes(tmp_path):
    """Dedup is content-based: a quarantine for a different before-state (a new
    wipe) must still be recorded after a previous one."""
    before = tmp_path / "before.ics"
    log = tmp_path / "changelog.jsonl"
    before.write_text(
        _cal(_sanitized("a@g", "20260713", "20260722") + _sanitized("b@g", "20260901", "20260910")),
        encoding="utf-8",
    )
    assert _run_quarantine(before, log, 1) == "recorded"
    before.write_text(
        _cal(_sanitized("c@g", "20261001", "20261010") + _sanitized("d@g", "20261101", "20261110")),
        encoding="utf-8",
    )
    assert _run_quarantine(before, log, 2) == "recorded"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2


def test_pii_and_quarantine_guards_ignore_each_other(tmp_path):
    """A leak and a blocked wipe can persist simultaneously (a details-mode
    feed whose only events are single-day all-day ones trips the tripwire yet
    sanitizes to an empty candidate). Each channel's record must not reset the
    other's dedup, else both alerts re-fire and the public ledger grows two
    records every hourly run."""
    before = tmp_path / "before.ics"
    log = tmp_path / "changelog.jsonl"
    before.write_text(
        _cal(_sanitized("a@g", "20260713", "20260722") + _sanitized("b@g", "20260901", "20260910")),
        encoding="utf-8",
    )
    # Hour 1: both alert once. Hours 2-3: both stay quiet despite alternation.
    assert _run_pii(log, 1) == "recorded"
    assert _run_quarantine(before, log, 1) == "recorded"
    assert _run_pii(log, 2) == "already"
    assert _run_quarantine(before, log, 2) == "duplicate"
    assert _run_pii(log, 3) == "already"
    assert _run_quarantine(before, log, 3) == "duplicate"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2
