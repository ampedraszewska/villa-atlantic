"""Villa Atlantic change ledger.

Appends an append-only audit record of every booking date that appears,
disappears, or moves in a calendar feed. The ledger (``ical/changelog.jsonl``)
is committed to git, so it is a permanent record that outlives Google's 30-day
deleted-events bin: every date that ever existed, and the moment our sync first
noticed it gone, stays recoverable forever.

One JSON object per line. Diff actions:

    added      a UID present in the new feed but not the old one
    removed    a UID gone from the new feed (carries last-known start/end)
    modified   a UID whose start/end changed (carries prev_* and new values)
    quarantined  emitted instead of a diff when the wipe guard blocked a feed;
                 records the attempted wipe without touching the live bookings

``created`` / ``last_modified`` are Google's own timestamps, lifted from the raw
feed (the sanitized feed strips them). ``detected_at`` + ``run_url`` + ``sha``
record when *our pipeline* observed the change.

CLI (used by the sync workflow):

    # normal diff after a feed is promoted
    python3 scripts/log_ical_changes.py --apt cliffs \\
        --before before.ics --after after.ics --raw cliffs.raw.ics \\
        --changelog ical/changelog.jsonl --run-url URL --sha SHA

    # record a blocked wipe (no live change)
    python3 scripts/log_ical_changes.py --apt cliffs --quarantined \\
        --before before.ics --changelog ical/changelog.jsonl --run-url URL --sha SHA
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib

from sanitize_ical import parse_events


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def diff_events(before_text: str, after_text: str, raw_text: str) -> list[dict]:
    """Return change records (without metadata) for before -> after.

    ``raw_text`` supplies CREATED / LAST-MODIFIED for added/modified events."""
    before = parse_events(before_text)
    after = parse_events(after_text)
    raw = parse_events(raw_text)
    records: list[dict] = []

    for uid in after.keys() - before.keys():
        ev, meta = after[uid], raw.get(uid, {})
        records.append(
            {
                "action": "added",
                "uid": uid,
                "start": ev["start"],
                "end": ev["end"],
                "created": meta.get("created"),
                "last_modified": meta.get("last_modified"),
            }
        )

    for uid in before.keys() - after.keys():
        ev = before[uid]
        records.append(
            {
                "action": "removed",
                "uid": uid,
                "start": ev["start"],
                "end": ev["end"],
                "created": None,
                "last_modified": None,
            }
        )

    for uid in before.keys() & after.keys():
        b, a = before[uid], after[uid]
        if (b["start"], b["end"]) != (a["start"], a["end"]):
            meta = raw.get(uid, {})
            records.append(
                {
                    "action": "modified",
                    "uid": uid,
                    "prev_start": b["start"],
                    "prev_end": b["end"],
                    "start": a["start"],
                    "end": a["end"],
                    "created": meta.get("created"),
                    "last_modified": meta.get("last_modified"),
                }
            )

    # Deterministic order so the same change always serializes identically.
    records.sort(key=lambda r: (r["action"], r["start"] or "", r["uid"]))
    return records


def quarantine_record(before_text: str) -> dict:
    """One record describing a blocked wipe (bookings preserved, not removed)."""
    before = parse_events(before_text)
    return {
        "action": "quarantined",
        "before_count": len(before),
        "preserved": [
            {"uid": uid, "start": ev["start"], "end": ev["end"]}
            for uid, ev in sorted(before.items(), key=lambda kv: (kv[1]["start"] or "", kv[0]))
        ],
    }


def _stamp(record: dict, apt: str, detected_at: str, run_url: str, sha: str) -> dict:
    """Prefix shared metadata onto a record (apartment + when-we-noticed)."""
    return {
        "detected_at": detected_at,
        "apartment": apt,
        **record,
        "run_url": run_url,
        "sha_before": sha,
    }


def _read(path: str | None) -> str:
    if not path:
        return ""
    p = pathlib.Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _main() -> int:
    ap = argparse.ArgumentParser(description="Append calendar change records to the ledger.")
    ap.add_argument("--apt", required=True, help="apartment name, e.g. cliffs / gardens")
    ap.add_argument("--changelog", required=True, help="path to changelog.jsonl")
    ap.add_argument("--before", help="previous sanitized feed")
    ap.add_argument("--after", help="new sanitized feed")
    ap.add_argument("--raw", help="raw feed (for CREATED / LAST-MODIFIED)")
    ap.add_argument("--quarantined", action="store_true", help="record a blocked wipe")
    ap.add_argument("--run-url", default="", help="GitHub Actions run URL")
    ap.add_argument("--sha", default="", help="commit sha of the before-state")
    ap.add_argument("--detected-at", default=None, help="override timestamp (ISO 8601 Z)")
    args = ap.parse_args()

    detected_at = args.detected_at or _now_iso()
    if args.quarantined:
        records = [quarantine_record(_read(args.before))]
    else:
        records = diff_events(_read(args.before), _read(args.after), _read(args.raw))

    if not records:
        return 0

    out = pathlib.Path(args.changelog)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        for rec in records:
            line = _stamp(rec, args.apt, detected_at, args.run_url, args.sha)
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
