"""The verdict rules every browser rung shares.

Rung 1 judges raw HTML, so it treats a client-side shell as a failed fetch. A
browser has already run the page's JavaScript by the time it reports, which
removes rung 1's two HTML-only rules and leaves the rest. That divergence is
the point of this file: the same page shape must not read the same way on two
rungs that saw different things.
"""

from __future__ import annotations

import pytest

from ladder_cli.rungs import RungVerdict, browser_judge, http, network_verdict, normalize_page_text


def page(title: str, text: str, status: int | None = 200) -> dict:
    return {"title": title, "text": text, "status": status}


def article(length: int = 900) -> str:
    return "An article opening. " + ("content " * (length // 8))


def shell(length: int = 900) -> str:
    return "Loading... " + ("nav " * (length // 4))


def test_real_content_passes() -> None:
    result = browser_judge(page("An article", article()))
    assert result.verdict is RungVerdict.OK
    assert result.status == 200


@pytest.mark.parametrize("status", [404, 410, 521, 522, 523, 525, 526, 530])
def test_a_gone_or_dead_origin_is_dead_and_does_not_climb(status: int) -> None:
    result = browser_judge(page("Not found", article(), status=status))
    assert result.verdict is RungVerdict.DEAD, "no stronger rung revives a deleted page"
    assert result.reason == f"status {status}"


def test_a_defended_page_still_climbs() -> None:
    result = browser_judge(page("Access denied", "nope", status=403))
    assert result.verdict is RungVerdict.BLOCKED
    assert result.reason == "status 403"


def test_a_bot_check_is_blocked_even_when_the_browser_ran() -> None:
    text = "Just a moment... checking your browser before you continue."
    result = browser_judge(page("Attention Required", text))
    assert result.verdict is RungVerdict.BLOCKED
    assert result.reason == "challenge marker"


def test_a_page_thinner_than_the_measured_floor_climbs() -> None:
    # ladder.py:133 `if len(rec["text"]) < 800`, applied to every rung
    result = browser_judge(page("Home", "Home and little else."))
    assert result.verdict is RungVerdict.BLOCKED
    assert "under the measured floor" in result.reason


def test_a_client_side_shell_is_content_on_a_browser_rung_but_not_on_rung_one() -> None:
    """The same page reads differently because the two rungs saw different things.

    ladder.py:122 gates the loading-shell rule on `rung == "http"`: by rung 2
    the JavaScript has already run, so a shell that survived that is the page,
    not a failed fetch. rung 1 has no such evidence and stays suspicious.
    """
    text = shell()
    assert http.judge(page("App", text)).verdict is RungVerdict.BLOCKED
    assert browser_judge(page("App", text)).verdict is RungVerdict.OK


def test_a_short_shell_on_a_browser_rung_is_judged_by_length_alone() -> None:
    """No shell rule survives on a browser rung, so only the floor is left.

    711 characters is under the measured floor, which is what makes it climb;
    the loading marker in it is not consulted.
    """
    result = browser_judge(page("App", shell(700)))
    assert result.verdict is RungVerdict.BLOCKED
    assert "under the measured floor" in result.reason


def test_run_blanks_are_collapsed_at_the_fetch_boundary_not_inside_the_judge() -> None:
    """ladder.py:114 normalised in the rung child, before the record was written.

    So the 800-character floor and the 600-character challenge window were both
    measured against the collapsed string. This is why the normalization belongs
    to the fetch rather than to the judge: a rung that hands its judge the raw
    innerText reads whitespace as content, and the two measured thresholds move
    onto text the run never saw.
    """
    padded = "Body text.\n" + "\n" * 900
    assert len(padded) > 800, "the padding alone must be enough to clear the floor"

    # What the rung hands its judge is the collapsed string...
    assert len(normalize_page_text(padded)) < 800
    assert browser_judge(page("Title", normalize_page_text(padded))).verdict is RungVerdict.BLOCKED

    # ...so a rung that skips it reads the padding as a page and stops the climb.
    raw = browser_judge(page("Title", padded))
    assert raw.verdict is RungVerdict.OK, "raw text reads as a page, which is the regression"
    assert raw.reason == f"{len(padded)} chars"


def test_normalization_is_idempotent_and_has_no_leading_or_trailing_space() -> None:
    assert normalize_page_text("\n\n  Body  \n\n\n") == "Body"
    assert normalize_page_text(None) == ""
    assert normalize_page_text("Body") == "Body"


def test_a_gone_domain_is_dead_on_rung_one_only() -> None:
    """ladder.py:192 gates the same mapping on the rung, so this must too.

    No browser revives a domain that does not resolve, so rung 1 reads it ``dead``
    and stops. A browser rung that cannot connect failed *itself*, and reading
    that as ``dead`` would stop the climb on exactly the signal that says to keep
    going: a stronger rung is allowed an answer.
    """
    message = "DNSError: failed to lookup address"

    assert network_verdict(message, "http") is RungVerdict.DEAD, "rung 1 is final"
    assert network_verdict(message, "camoufox") is RungVerdict.ERROR, "rung 2 climbs"
    assert network_verdict(message, "zendriver_cf") is RungVerdict.ERROR
    assert network_verdict(message, "zendriver_headed_cf") is RungVerdict.ERROR


def test_a_browser_rungs_own_failure_climbs_rather_than_finishing_the_climb() -> None:
    assert network_verdict("TimeoutError: navigation timed out", "camoufox") is RungVerdict.ERROR
    assert network_verdict("something nobody mapped", "zendriver_cf") is RungVerdict.ERROR
