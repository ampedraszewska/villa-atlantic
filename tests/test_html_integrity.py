"""Static checks against index.html. No browser, no server — just
BeautifulSoup parsing the committed source.

Each test pins a specific invariant that was broken at least once in the
history of this repo, or would cause silent damage if it ever drifted
(PL/EN coverage gap, wrong domain in OG tags, stale placeholder strings,
missing image assets).
"""

from __future__ import annotations

import pathlib
import re
from collections import Counter

import pytest
from bs4 import BeautifulSoup

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
CNAME_FILE = REPO_ROOT / "CNAME"


@pytest.fixture(scope="module")
def html_text() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def soup(html_text: str) -> BeautifulSoup:
    return BeautifulSoup(html_text, "html.parser")


@pytest.fixture(scope="module")
def cname_domain() -> str:
    return CNAME_FILE.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Placeholders that must never survive to committed HTML.
# ---------------------------------------------------------------------------

# Each entry is (regex, human-readable reason).
PLACEHOLDER_PATTERNS: list[tuple[str, str]] = [
    (r"VV-XXXXX", "VV license placeholder"),
    (r"YOUR_[A-Z_]+", "YOUR_ prefixed env placeholder"),
    (r"\+48 000 000 000", "phone number placeholder"),
    (r"wa\.me/48000000000", "WhatsApp href placeholder"),
    (r"\blorem ipsum\b", "lorem ipsum filler text"),
    (r"\bTODO:", "TODO: marker in shipped code"),
    (r"\bFIXME\b", "FIXME marker"),
    (r"\bTBD\b", "TBD marker"),
]


def test_no_placeholder_patterns(html_text: str):
    for pattern, reason in PLACEHOLDER_PATTERNS:
        matches = re.findall(pattern, html_text, flags=re.IGNORECASE)
        assert not matches, (
            f"placeholder survived in index.html: {pattern!r} ({reason}); occurrences={matches[:3]}"
        )


# ---------------------------------------------------------------------------
# Inquiry form: hidden fields and action endpoint.
# ---------------------------------------------------------------------------


def _form(soup: BeautifulSoup):
    form = soup.select_one("form.inquiry-form")
    assert form is not None, "no form.inquiry-form found"
    return form


def test_form_action_points_to_formsubmit(soup: BeautifulSoup):
    form = _form(soup)
    action = form.get("action", "")
    assert action.startswith("https://formsubmit.co/"), (
        f"form action should go to formsubmit.co, got {action!r}"
    )
    # The address must look plausible — at least one '@' inside the path.
    assert "@" in action, f"formsubmit endpoint missing email: {action!r}"


def test_form_has_hidden_next_redirect(soup: BeautifulSoup):
    """The _next hidden field is what makes formsubmit.co redirect guests
    back to our site after submit instead of to its generic branded
    thank-you page. Guards against a regression where someone drops the
    field while editing the form."""
    form = _form(soup)
    assert form.find("input", {"name": "_next"}) is not None, (
        'form must have a hidden input name="_next"'
    )


def test_form_has_hidden_subject(soup: BeautifulSoup):
    form = _form(soup)
    assert form.find("input", {"name": "_subject"}) is not None, (
        'form must have a hidden input name="_subject" for readable inbox'
    )


# ---------------------------------------------------------------------------
# Domain consistency: CNAME, canonical, og:url must all agree.
# ---------------------------------------------------------------------------


def test_cname_file_set_to_production_domain(cname_domain: str):
    assert cname_domain, "CNAME file is empty"
    # Must be a plain domain (no scheme, no path).
    assert re.match(r"^[a-z0-9.-]+$", cname_domain), (
        f"CNAME should be a bare domain, got {cname_domain!r}"
    )


def test_canonical_link_matches_cname(soup: BeautifulSoup, cname_domain: str):
    link = soup.find("link", rel="canonical")
    assert link is not None, "no <link rel=canonical> found"
    href = link.get("href", "")
    assert cname_domain in href, (
        f"<link rel=canonical href={href!r}> does not reference CNAME domain {cname_domain!r}"
    )


def test_og_url_matches_cname(soup: BeautifulSoup, cname_domain: str):
    og = soup.find("meta", property="og:url")
    assert og is not None, "no <meta property=og:url> found"
    content = og.get("content", "")
    assert cname_domain in content, (
        f"og:url={content!r} does not reference CNAME domain {cname_domain!r}"
    )


# ---------------------------------------------------------------------------
# Language parity: every element with data-lang="en" must have a counterpart
# with data-lang="pl" in the same parent (and vice versa).
# ---------------------------------------------------------------------------


def test_every_en_element_has_pl_counterpart_in_same_parent(
    soup: BeautifulSoup,
):
    offenders: list[str] = []
    # Group elements by parent; each parent must have balanced lang counts.
    parents_with_lang: dict[int, dict[str, int]] = {}
    for el in soup.find_all(attrs={"data-lang": True}):
        lang = el.get("data-lang")
        parent_id = id(el.parent)
        bucket = parents_with_lang.setdefault(parent_id, Counter())
        bucket[lang] += 1

    for parent_id, counts in parents_with_lang.items():
        en = counts.get("en", 0)
        pl = counts.get("pl", 0)
        if en != pl:
            # Find the parent back for a useful error message.
            parent = next(
                (
                    el.parent
                    for el in soup.find_all(attrs={"data-lang": True})
                    if id(el.parent) == parent_id
                ),
                None,
            )
            tag_name = getattr(parent, "name", "?")
            offenders.append(f"<{tag_name}> has en={en} pl={pl} data-lang children")

    assert not offenders, (
        "language-parity mismatch (each element with data-lang=en needs "
        "a data-lang=pl sibling in the same parent):\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Local asset references must exist on disk — otherwise site ships with 404s.
# ---------------------------------------------------------------------------


def _local_src(src: str) -> bool:
    return bool(src) and not src.startswith(
        ("http://", "https://", "data:", "//", "mailto:", "tel:")
    )


def test_local_image_srcs_exist_on_disk(soup: BeautifulSoup):
    missing: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not _local_src(src):
            continue
        path = REPO_ROOT / src.lstrip("/")
        if not path.exists():
            missing.append(src)
    assert not missing, f"<img src> references missing files: {missing}"


def test_local_video_and_poster_exist_on_disk(soup: BeautifulSoup):
    missing: list[str] = []
    for video in soup.find_all("video"):
        poster = video.get("poster", "")
        if _local_src(poster) and not (REPO_ROOT / poster.lstrip("/")).exists():
            missing.append(f"poster={poster}")
        for source in video.find_all("source"):
            src = source.get("src", "")
            if _local_src(src) and not (REPO_ROOT / src.lstrip("/")).exists():
                missing.append(f"video src={src}")
        src = video.get("src", "")
        if _local_src(src) and not (REPO_ROOT / src.lstrip("/")).exists():
            missing.append(f"video src={src}")
    assert not missing, f"<video> asset(s) missing: {missing}"


# ---------------------------------------------------------------------------
# JS-embedded iCal URL constants must not be default placeholder strings.
# The production guard logic depends on them NOT equalling the sentinel.
# ---------------------------------------------------------------------------

_ICAL_CONST_RE = re.compile(r"const\s+ICAL_(CLIFFS|GARDENS)\s*=\s*'([^']*)'")


def test_ical_constants_not_default_placeholders(html_text: str):
    matches = _ICAL_CONST_RE.findall(html_text)
    assert len(matches) == 2, f"expected two ICAL_ constants, got {len(matches)}: {matches}"
    for name, value in matches:
        assert value != f"{name}_ICAL_URL", f"ICAL_{name} still set to default placeholder"
        # Must point to an https URL or a local same-origin path.
        assert value.startswith(("https://", "ical/", "/ical/")), (
            f"ICAL_{name} = {value!r} does not look like a URL or same-origin path"
        )


# ---------------------------------------------------------------------------
# HTTPS + integrity on third-party scripts we load by URL.
# (Catches a mistyped CDN URL like what caused the ical.js peer-dep regression
# — a fresh test_ical_constants doesn't cover that class of problem.)
# ---------------------------------------------------------------------------


def test_third_party_scripts_use_https(html_text: str):
    """Scan JS source for http:// (not https) in loadScript / loadStyle
    arguments so we fail fast on a mixed-content regression."""
    insecure = re.findall(
        r"loadScript\(\s*'http://[^']+'",
        html_text,
    )
    insecure += re.findall(r"loadStyle\(\s*'http://[^']+'", html_text)
    assert not insecure, f"insecure http:// CDN in loadScript/Style: {insecure}"


def test_ical_js_peer_dep_is_loaded_before_icalendar_plugin(html_text: str):
    """Regression guard for the silent FullCalendar bug: the
    @fullcalendar/icalendar plugin needs ical.js to be loaded first.
    Find the order of these two script URLs in loadFullCalendar()."""
    ical_js_pos = html_text.find("ical.js@")
    plugin_pos = html_text.find("@fullcalendar/icalendar@")
    assert ical_js_pos != -1, "ical.js peer dep not loaded anywhere"
    assert plugin_pos != -1, "@fullcalendar/icalendar not loaded anywhere"
    assert ical_js_pos < plugin_pos, (
        "ical.js must be loaded BEFORE @fullcalendar/icalendar — "
        "otherwise the plugin silently drops all format:'ics' sources"
    )
