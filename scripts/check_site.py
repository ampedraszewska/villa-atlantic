#!/usr/bin/env python3
"""Liveness canary for the published site.

Fetches the LIVE site and asserts it is actually serving the villa page — not
merely returning some HTTP 200. Run by .github/workflows/uptime.yml every 15
minutes; exits non-zero with one line per failure.

Why more than a status-code check: on 2026-08-02 the GitHub Pages site was
disabled in repo settings. Every workflow stayed green for as long as it took
someone to notice by hand, because nothing here ever fetched the live origin.
GitHub's own "Site not found" page is a 404, but a parked domain, a hijacked
NS, or an empty deploy all answer 200 — hence the content markers.

The domain is read from the CNAME file, so this and GitHub Pages can never
disagree about which host is production.
"""

from __future__ import annotations

import argparse
import socket
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

CNAME_FILE = Path(__file__).resolve().parent.parent / "CNAME"

# Strings that must appear in the served page. Together they distinguish the
# real site from any other 200: the <title>, and the canonical/og URL that only
# this site's HTML carries.
PAGE_MARKERS = ("Villa Atlantic", "<title>", "canonical")
ICS_PATHS = ("/ical/cliffs.ics", "/ical/gardens.ics")
MIN_CERT_DAYS = 14
TIMEOUT = 20
USER_AGENT = "villa-atlantic-uptime-canary"


def production_domain(cname_file: Path = CNAME_FILE) -> str:
    return cname_file.read_text(encoding="utf-8").strip()


def fetch(url: str, timeout: int = TIMEOUT) -> tuple[int, str]:
    """Return (status, body). Status 0 means the request never completed."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # DNS failure, TLS failure, timeout, refused
        return 0, f"{type(e).__name__}: {e}"


def check_page(url: str, fetcher=fetch) -> list[str]:
    status, body = fetcher(url)
    if status != 200:
        return [f"{url} -> HTTP {status} ({body.splitlines()[0][:120] if body else 'no body'})"]
    missing = [m for m in PAGE_MARKERS if m not in body]
    if missing:
        return [f"{url} -> HTTP 200 but the page is not ours; missing: {', '.join(missing)}"]
    return []


def check_ics(url: str, fetcher=fetch) -> list[str]:
    status, body = fetcher(url)
    if status != 200:
        return [f"{url} -> HTTP {status} (calendar would render empty)"]
    if not body.lstrip().startswith("BEGIN:VCALENDAR"):
        return [f"{url} -> HTTP 200 but not an iCalendar feed; starts with {body[:40]!r}"]
    return []


def cert_days_left(host: str, port: int = 443, timeout: int = TIMEOUT) -> int:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]
    expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    return (expiry - datetime.now(UTC)).days


def check_cert(host: str, days_fn=cert_days_left) -> list[str]:
    try:
        days = days_fn(host)
    except Exception as e:
        return [f"{host} -> TLS handshake failed: {type(e).__name__}: {e}"]
    if days < MIN_CERT_DAYS:
        return [f"{host} -> TLS certificate expires in {days}d (below {MIN_CERT_DAYS}d)"]
    return []


def run_checks(domain: str, fetcher=fetch, days_fn=cert_days_left) -> list[str]:
    """Every failure, not just the first — one run should report the whole picture."""
    failures = check_page(f"https://{domain}/", fetcher)
    failures += check_page(f"https://www.{domain}/", fetcher)
    for path in ICS_PATHS:
        failures += check_ics(f"https://{domain}{path}", fetcher)
    failures += check_cert(domain, days_fn)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--domain",
        default=None,
        help="Domain to check (default: the contents of the repo's CNAME file).",
    )
    args = parser.parse_args()
    try:
        domain = args.domain or production_domain()
    except OSError as e:
        # A deleted CNAME is itself an outage (Pages falls back to the
        # github.io host). Report it as one: a traceback would leave the
        # workflow with an empty report and therefore no alert at all.
        print(f"DOWN — cannot read {CNAME_FILE}: {e}")
        return 1

    failures = run_checks(domain)
    if failures:
        print(f"DOWN — {len(failures)} check(s) failed for {domain}:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print(f"OK — {domain} is serving the site, both calendars, and a valid certificate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
