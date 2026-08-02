"""Tests for scripts/check_site.py — the live-site liveness canary.

The canary exists because a status code alone is not evidence the site is up:
the 2026-08-02 outage served GitHub's own 404, and a parked or hijacked domain
would serve a 200 that is not this site at all. So the checks that matter are
the ones that fail on a *plausible* wrong answer, and those are what is pinned
here.
"""

import check_site
import pytest
from check_site import check_cert, check_ics, check_page, main, production_domain, run_checks

REAL_PAGE = '<html><head><title>Villa Atlantic</title><link rel="canonical" href="/"></head></html>'
GITHUB_404 = "<html><head><title>Site not found &middot; GitHub Pages</title></head></html>"
REAL_ICS = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"


def _fetcher(responses):
    """A fetch() stand-in serving canned (status, body) per URL."""

    def fetch(url, timeout=None):
        return responses.get(url, (404, GITHUB_404))

    return fetch


def test_healthy_page_passes():
    assert check_page("https://x/", _fetcher({"https://x/": (200, REAL_PAGE)})) == []


@pytest.mark.parametrize(
    "response",
    [
        (404, GITHUB_404),  # the actual 2026-08-02 outage
        (0, "URLError: [Errno 8] nodename nor servname provided"),  # DNS gone
        (500, "boom"),
        (200, GITHUB_404),  # a 200 that is not our page
        (200, "<html><title>Domain for sale</title></html>"),  # parked domain
        (200, ""),  # empty deploy
    ],
)
def test_page_failures_are_caught(response):
    assert check_page("https://x/", _fetcher({"https://x/": response})) != []


def test_healthy_ics_passes():
    assert (
        check_ics("https://x/ical/a.ics", _fetcher({"https://x/ical/a.ics": (200, REAL_ICS)})) == []
    )


@pytest.mark.parametrize(
    "response",
    [
        (404, "gone"),  # feed missing -> calendar silently renders empty
        (200, "<!DOCTYPE html>"),  # SPA fallback served instead of the feed
        (200, ""),
    ],
)
def test_ics_failures_are_caught(response):
    url = "https://x/ical/a.ics"
    assert check_ics(url, _fetcher({url: response})) != []


@pytest.mark.parametrize(
    "days,expected_failure", [(90, False), (15, False), (14, False), (13, True), (0, True)]
)
def test_cert_expiry_threshold(days, expected_failure):
    assert bool(check_cert("x", lambda host: days)) is expected_failure


def test_cert_handshake_failure_is_caught():
    def boom(host):
        raise ConnectionRefusedError("refused")

    assert check_cert("x", boom) != []


def test_run_checks_reports_every_failure_not_just_the_first():
    """One run must show the whole picture, so a fix is not a game of whack-a-mole."""
    all_dead = _fetcher({})
    failures = run_checks("x", all_dead, lambda host: 0)
    # apex + www + 2 calendars + certificate
    assert len(failures) == 5


def test_run_checks_passes_on_a_fully_healthy_site():
    healthy = _fetcher(
        {
            "https://x/": (200, REAL_PAGE),
            "https://www.x/": (200, REAL_PAGE),
            "https://x/ical/cliffs.ics": (200, REAL_ICS),
            "https://x/ical/gardens.ics": (200, REAL_ICS),
        }
    )
    assert run_checks("x", healthy, lambda host: 90) == []


def test_domain_comes_from_the_cname_file():
    """Pages reads CNAME too; a second hardcoded copy is how the two drift apart."""
    assert production_domain() == "atlanticvilla.net"


def test_missing_cname_reports_an_outage_instead_of_a_traceback(monkeypatch, capsys):
    """A deleted CNAME is an outage, and the workflow builds its alert from stdout.

    A traceback goes to stderr and leaves stdout empty, which would file the
    alert issue with a blank title and no body — the one outage nobody hears
    about.
    """

    def gone(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(check_site, "production_domain", gone)
    monkeypatch.setattr("sys.argv", ["check_site.py"])

    assert main() == 1
    assert capsys.readouterr().out.startswith("DOWN")
