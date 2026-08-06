"""Static checks against .github/workflows/alert-router.yml.

The router is the only alerting that survives a job dying before its own alert
step runs, so every invariant below is one that, if it silently drifted, would
put us back to where we were on 2026-08-06: two failed runs, nobody told.

Assertions are on the raw text rather than a parsed tree on purpose. PyYAML is
not in requirements-dev.txt and is not a transitive dependency of bs4 or
icalendar, so `import yaml` would pass locally and fail CI; adding a dependency
to check a handful of literal lines is not worth it, and pinning the exact
load-bearing line is what these tests are for anyway.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ROUTER = WORKFLOWS / "alert-router.yml"
UPTIME = WORKFLOWS / "uptime.yml"


@pytest.fixture(scope="module")
def router() -> str:
    return ROUTER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def uptime() -> str:
    return UPTIME.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# What is monitored.
# ---------------------------------------------------------------------------

# GitHub reports two spellings for the generated Pages workflow (the workflows
# API vs. a run object), and only one of them can be the one that matches.
MONITORED = (
    "Uptime canary",
    "Sync iCal feeds",
    "pages-build-deployment",
    "pages build and deployment",
)


def test_router_is_triggered_by_completed_runs_of_other_workflows(router: str):
    assert "workflow_run:" in router, (
        "the router must run out-of-band, not inside the monitored job"
    )
    assert "types: [completed]" in router


@pytest.mark.parametrize("name", MONITORED)
def test_router_watches_the_unattended_workflows(router: str, name: str):
    assert f"      - {name}\n" in router, f"{name} is unmonitored"


@pytest.mark.parametrize("name", ["CI", "Lint"])
def test_router_ignores_the_pr_workflows(router: str, name: str):
    # A CI or Lint failure is already visible in the pull request; an alert issue
    # for it is noise that teaches you to ignore the alerts that matter.
    assert f"- {name}\n" not in router, f"{name} should not be monitored"


def test_router_ignores_pr_runs(router: str):
    # sync-ical.yml and the Pages build also run off main. Those failures belong
    # in the PR, and the gate has to sit on the job so it is evaluated before a
    # runner is claimed.
    assert "github.event.workflow_run.head_branch == 'main'" in router


def test_router_acts_on_every_terminal_conclusion_including_timeouts(router: str):
    """timed_out has to be in the allow-list.

    It is a real workflow_run conclusion, distinct from failure, and a
    timeout-minutes kill is a genuine failure of our own code that left executed
    steps behind. Dropping it here would put the timeout case back into exactly
    the silence this router exists to end — and it would do so invisibly,
    because the suppression below would never even see the run.
    """
    assert 'contains(fromJSON(\'["success","failure","timed_out"]\')' in router


# ---------------------------------------------------------------------------
# Infrastructure-failure suppression.
# ---------------------------------------------------------------------------


def test_router_suppresses_runner_acquisition_failures(router: str):
    """Zero executed steps across every job means GitHub never handed out a
    runner — the 2026-08-06 canary failure. Nothing of ours ran, so there is
    nothing to alert about, and mailing on it is what trains you to ignore the
    mail."""
    assert "'[.jobs[].steps[]] | length'" in router
    assert 'if [ "$steps_run" = "0" ]; then' in router
    assert "GITHUB_STEP_SUMMARY" in router, "a suppressed failure must still leave a trace"


def test_suppression_keys_on_step_count_never_on_the_conclusion(router: str):
    """A timeout-minutes kill DOES leave executed steps behind and must still
    alert. The moment the suppression starts matching on a conclusion string
    instead of the step count, a real hang gets swallowed. The 2026-08-06 canary
    run reported its job as cancelled, so that string is the tempting shortcut
    and the one that must never appear here."""
    assert "cancelled" not in router


def test_unreadable_jobs_list_falls_through_to_alerting(router: str):
    # Failing open is the entire point of this file: an API hiccup must cost a
    # spurious alert, never a silent one.
    assert "|| steps_run=unknown" in router


# ---------------------------------------------------------------------------
# Dedup key. The router must never open a second issue next to an in-job alert.
# ---------------------------------------------------------------------------


def test_dedup_key_is_the_monitored_workflow_filename(router: str):
    assert 'key="$(basename "$WF_PATH" .yml)"' in router
    assert "WF_PATH: ${{ github.event.workflow_run.path }}" in router


def test_dedup_key_matches_the_label_uptime_yml_already_files_under(uptime: str):
    """The drift guard that makes the whole no-mapping-table design safe.

    The router derives its issue label from the monitored workflow's filename,
    so uptime.yml's own label has to equal its own filename stem. Rename either
    and the two alert paths stop deduplicating against each other: an outage
    would file two issues, and uptime.yml's close-on-green would leave the
    router's behind, open forever.
    """
    label = re.search(r"^\s*LABEL:\s*(\S+)\s*$", uptime, flags=re.MULTILINE)
    assert label, "uptime.yml no longer declares a LABEL"
    assert label.group(1) == UPTIME.stem, (
        f"uptime.yml files under label {label.group(1)!r} but the router will "
        f"derive {UPTIME.stem!r} from its filename"
    )


def test_router_stands_down_when_an_alert_is_already_open(router: str):
    # Covers both "the monitored workflow alerted itself, with a richer body"
    # and "we alerted on an earlier run of the same outage". One open issue per
    # outage is one email per outage, not one every 15 minutes.
    assert 'gh issue list --label "$key" --state open' in router
    assert "not filing a duplicate" in router


def test_router_closes_the_alert_on_the_next_green_run(router: str):
    assert 'if [ "$CONCLUSION" = "success" ]; then' in router
    assert 'gh issue close "$open_num"' in router


# ---------------------------------------------------------------------------
# The alert channel itself.
# ---------------------------------------------------------------------------


def test_alert_is_an_issue_assigned_to_the_owner(router: str):
    # Assignment is what generates the email, and it arrives under
    # "Participating" — a different notification category from the per-run
    # Actions email, which is switched off account-wide.
    assert '--assignee "$OWNER"' in router
    assert "OWNER: ${{ github.repository_owner }}" in router
    assert "issues: write" in router
    assert "actions: read" in router


def test_uptime_yml_assigns_its_own_alert_too(uptime: str):
    # Both alert paths have to notify identically, otherwise which channel you
    # hear about an outage on depends on which step happened to survive.
    assert '--assignee "$OWNER"' in uptime
    assert "OWNER: ${{ github.repository_owner }}" in uptime


@pytest.mark.parametrize("leak", ["html_url", "server_url", "RUN_URL"])
def test_alert_body_leaks_no_run_url_into_a_public_issue(router: str, leak: str):
    # This repository is public. The issue carries the workflow name and nothing
    # else; the detail stays in the Actions tab.
    assert leak not in router


@pytest.mark.parametrize("channel", ["DISCORD", "webhook", "curl"])
def test_notifications_are_email_only(router: str, channel: str):
    assert channel not in router
