"""Villa Atlantic booking recovery.

Reads the append-only ledger (``ical/changelog.jsonl``) written by
log_ical_changes.py and lets you (a) see every booking that ever existed and
which ones are currently gone, and (b) republish a removed booking to the live
site even after Google's 30-day bin has purged it.

    # what's been lost?
    python3 scripts/restore_booking.py --report

    # put a removed booking back on the public site
    python3 scripts/restore_booking.py --reinstate <uid> --apt cliffs

The ledger stores already-sanitized (checkout-shifted) dates, so reinstating
writes the event straight into the live ``ical/<apt>.ics`` — it must NOT be run
back through sanitize_ical (that would shift the checkout day a second time).
Recreating the booking inside Google Calendar stays a manual step; --report
hands you the exact dates to retype there.
"""

from __future__ import annotations

import argparse
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CHANGELOG = REPO_ROOT / "ical" / "changelog.jsonl"


def load_ledger(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def reconstruct(records: list[dict]) -> dict[str, dict[str, dict]]:
    """Replay the ledger into current per-apartment booking state.

    Returns ``{apartment: {uid: {start, end, created, status, removed_at}}}``
    where status is 'present' or 'removed'. Quarantine records are skipped —
    they record a blocked wipe, not a real booking change."""
    state: dict[str, dict[str, dict]] = {}
    for rec in records:
        action = rec.get("action")
        if action == "quarantined":
            continue
        apt = rec.get("apartment", "?")
        uid = rec.get("uid")
        if not uid:
            continue
        bucket = state.setdefault(apt, {})
        if action in ("added", "modified"):
            bucket[uid] = {
                "start": rec.get("start"),
                "end": rec.get("end"),
                "created": rec.get("created"),
                "status": "present",
                "removed_at": None,
            }
        elif action == "removed":
            entry = bucket.get(uid, {"created": None})
            entry.update(
                {
                    "start": rec.get("start"),
                    "end": rec.get("end"),
                    "status": "removed",
                    "removed_at": rec.get("detected_at"),
                }
            )
            entry.setdefault("created", None)
            bucket[uid] = entry
    return state


def _report(state: dict[str, dict[str, dict]]) -> str:
    lines: list[str] = []
    for apt in sorted(state):
        bookings = state[apt]
        present = sorted(
            (u for u, e in bookings.items() if e["status"] == "present"),
            key=lambda u: bookings[u]["start"] or "",
        )
        removed = sorted(
            (u for u, e in bookings.items() if e["status"] == "removed"),
            key=lambda u: bookings[u]["start"] or "",
        )
        lines.append(f"=== {apt} ===")
        lines.append(f"  present ({len(present)}):")
        for u in present:
            e = bookings[u]
            lines.append(f"    {e['start']} -> {e['end']}  created {e['created']}  (uid {u})")
        lines.append(f"  REMOVED — recovery candidates ({len(removed)}):")
        for u in removed:
            e = bookings[u]
            lines.append(f"    {e['start']} -> {e['end']}  removed {e['removed_at']}  (uid {u})")
        lines.append("")
    return "\n".join(lines) if lines else "Ledger is empty — nothing recorded yet."


def _dt_property(prop: str, value: str) -> str:
    """Render a DTSTART/DTEND line from a ledger value.

    Date-only ledger values (``YYYY-MM-DD``) become
    ``<prop>;VALUE=DATE:YYYYMMDD``. Timed values are kept raw (e.g.
    ``20260713T100000Z``) and emitted without the ``VALUE=DATE`` parameter —
    tagging a date-time as ``VALUE=DATE`` violates RFC 5545 and makes parsers
    (FullCalendar's ical.js included) silently drop the time."""
    if "T" in value:
        return f"{prop}:{value}"
    return f"{prop};VALUE=DATE:{value.replace('-', '')}"


def build_vevent(uid: str, start: str, end: str) -> str:
    """A sanitized-style VEVENT block (CRLF, no trailing newline)."""
    return "\r\n".join(
        [
            "BEGIN:VEVENT",
            _dt_property("DTSTART", start),
            _dt_property("DTEND", end),
            f"UID:{uid}",
            "SUMMARY:Booked",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]
    )


def insert_event(ics_text: str, vevent: str) -> str:
    """Insert a VEVENT block immediately before END:VCALENDAR."""
    marker = "END:VCALENDAR"
    idx = ics_text.rfind(marker)
    if idx == -1:
        raise ValueError("live feed has no END:VCALENDAR — refusing to corrupt it")
    return ics_text[:idx] + vevent + "\r\n" + ics_text[idx:]


def reinstate(
    uid: str, state: dict[str, dict[str, dict]], apt: str | None
) -> tuple[str, str, str, str]:
    """Resolve a uid to (apartment, start, end). Raises if ambiguous/missing."""
    hits = [
        (a, bookings[uid])
        for a, bookings in state.items()
        if uid in bookings and (apt is None or a == apt)
    ]
    if not hits:
        raise SystemExit(
            f"uid {uid} not found in ledger" + (f" for apartment {apt}" if apt else "")
        )
    if len(hits) > 1:
        apts = ", ".join(a for a, _ in hits)
        raise SystemExit(
            f"uid {uid} exists in multiple apartments ({apts}); pass --apt to disambiguate"
        )
    found_apt, entry = hits[0]
    if not entry.get("start") or not entry.get("end"):
        raise SystemExit(f"uid {uid} has no recorded dates — cannot rebuild")
    return found_apt, entry["start"], entry["end"], entry["status"]


def _main() -> int:
    ap = argparse.ArgumentParser(description="Inspect and recover Villa Atlantic bookings.")
    ap.add_argument("--changelog", default=str(DEFAULT_CHANGELOG), help="path to changelog.jsonl")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--report", action="store_true", help="list every booking + recovery candidates"
    )
    mode.add_argument(
        "--reinstate", metavar="UID", help="republish a removed booking to the live feed"
    )
    ap.add_argument("--apt", help="apartment name (disambiguates --reinstate)")
    args = ap.parse_args()

    records = load_ledger(pathlib.Path(args.changelog))
    state = reconstruct(records)

    if args.report:
        print(_report(state))
        return 0

    found_apt, start, end, status = reinstate(args.reinstate, state, args.apt)
    live_path = REPO_ROOT / "ical" / f"{found_apt}.ics"
    if not live_path.exists():
        raise SystemExit(f"live feed not found: {live_path}")
    live = live_path.read_text(encoding="utf-8")
    if f"UID:{args.reinstate}" in live:
        print(f"uid {args.reinstate} already present in {live_path.name} — nothing to do.")
        return 0
    vevent = build_vevent(args.reinstate, start, end)
    live_path.write_text(insert_event(live, vevent), encoding="utf-8")
    note = "" if status == "removed" else " (was still marked present in ledger)"
    print(f"Reinstated {start} -> {end} into {live_path.name}{note}.")
    print(
        "Commit + push to publish. Recreate it in Google Calendar by hand "
        "to keep the feed authoritative."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
