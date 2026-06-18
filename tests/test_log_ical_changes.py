"""Tests for scripts/log_ical_changes.py — the change ledger."""

import json

from log_ical_changes import diff_events, quarantine_record


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
    import pathlib
    import subprocess
    import sys

    script = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "log_ical_changes.py"
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
