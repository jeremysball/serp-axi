"""Replay the measured run's recorded rows through the browser verdict rules.

Each case is a row the 100-domain run actually produced at rungs 2 to 4,
replayed against the deterministic verdict it recorded in its ``regex``
baseline. The page text was never checked in, only what the run recorded about
it (character count, status, and whether a bot-check marker was in reach), so
each case rebuilds a page carrying exactly those facts and no more.

Two facts the run did not record are marked rather than reconstructed, because
a number that looks measured and is not is worse than a gap: rows with no
recorded character count carry the ``UNRECORDED`` placeholder body, and rows
where only the status was recorded carry ``None`` rather than a 200 nobody
observed. Neither is load-bearing for the verdict the case asserts, and
pretending otherwise would let this file drift from the evidence without
anything noticing.

Where the run's Jev classifier disagreed with that baseline, the case names the
row. Those disagreements are the classifier's job, which lands in Phase 5;
asserting them here would claim a decision the deterministic rules never made.
"""

from __future__ import annotations

import pytest

from ladder_cli.rungs import MODULES, RungVerdict, camoufox, headed, zendriver

MODULES_BY_WIRE = {name: module for name, module in MODULES.items() if name != "http"}

# The spike's words -> ours. "thin" is the run's fourth word; it is not a
# distinct outcome for a caller, so it climbs like any other unmet page.
VERDICTS = {
    "ok": RungVerdict.OK,
    "thin": RungVerdict.BLOCKED,
    "blocked": RungVerdict.BLOCKED,
    "dead": RungVerdict.DEAD,
}

CHALLENGE_TEXT = "Just a moment... checking your browser before you continue."
BODY = "page body content "
UNRECORDED = "length the run did not record "


def build(chars: int | None, status: int | None, challenge: bool) -> dict:
    """A page carrying the recorded facts, with unrecorded ones marked as such."""
    filler = CHALLENGE_TEXT if challenge else (BODY if chars is not None else UNRECORDED)
    return {
        "title": "Recorded",
        "text": (filler * (chars // len(filler) + 1))[:chars] if chars is not None else filler,
        "status": status,
    }


# (url, rung, chars, status, had_challenge_marker, spike_regex, spike_jev_kind)
#
# zendriver returns no status at all (ladder.py:91 `return title, text, None`),
# so those rows carry None rather than a 200 the run never observed.
RECORDED = [
    # rung 2, camoufox
    ("https://t77772.com/", "camoufox", 6924, None, False, "ok", "content"),
    ("https://burgerkingrus.ru/", "camoufox", 8636, None, False, "ok", "content"),
    ("https://edwardburtynsky.com/", "camoufox", 113, None, False, "thin", "content"),
    ("https://sdfeiyate.com/", "camoufox", None, 403, False, "blocked", None),
    ("https://789p.moe/", "camoufox", None, 403, False, "blocked", None),
    # rung 3, zendriver + Turnstile click
    ("https://famishare.jp/", "zendriver_cf", 677, None, False, "thin", "dead"),
    ("https://sdfeiyate.com/", "zendriver_cf", 859, None, False, "ok", "challenge"),
    ("https://789p.moe/", "zendriver_cf", 255, None, True, "blocked", "challenge"),
    # rung 4, headed Chromium under Xvfb
    ("https://789p.moe/", "zendriver_headed_cf", 12750, None, False, "ok", "content"),
    ("https://sdfeiyate.com/", "zendriver_headed_cf", 859, None, False, "ok", "challenge"),
]


@pytest.mark.parametrize("url,rung,chars,status,challenge,spike,jev", RECORDED)
def test_a_recorded_row_reads_the_same_way_it_did_in_the_measured_run(
    url: str, rung: str, chars: int | None, status: int | None, challenge: bool, spike: str, jev: str | None
) -> None:
    result = MODULES_BY_WIRE[rung].judge(build(chars, status, challenge))
    assert result.verdict is VERDICTS[spike], f"{url} at {rung}: the run recorded {spike}, got {result.verdict.value}"
    assert result.status == status


@pytest.mark.parametrize("url,rung,chars,status,challenge,spike,jev", RECORDED)
def test_the_browser_rungs_apply_one_set_of_rules(
    url: str, rung: str, chars: int | None, status: int | None, challenge: bool, spike: str, jev: str | None
) -> None:
    """A page judged twice must not read differently because it climbed twice.

    This sweeps the browser rungs, not every module. `http` is deliberately a
    different rule set (rungs/__init__.py:12-13): rung 1 is the cheap fetch and
    its verdicts come from the network, not from reading a page. Sweeping all of
    MODULES.values() made this test fail for a reason unrelated to its purpose
    the moment http's judge diverged as designed, and it stopped naming what it
    covers when rung 5 joined the registry.
    """
    page = build(chars, status, challenge)
    browser = [module for name, module in MODULES.items() if name != "http"]
    verdicts = {module.judge(page).verdict for module in browser}
    assert len(verdicts) == 1, f"the browser rungs disagree about {url}"


def test_the_classifier_disagreements_are_left_for_phase_five() -> None:
    """Three recorded rows show the deterministic baseline and Jev splitting.

    Kept as facts rather than as assertions so Phase 5 starts from the size of
    the gap it has to close, and this file never claims to have closed it.
    """
    to_verdict = {"content": "ok", "challenge": "blocked", "dead": "dead", "loading_shell": "thin"}
    disagreements = [
        ("https://edwardburtynsky.com/", "camoufox", "thin", "content"),
        ("https://sdfeiyate.com/", "zendriver_cf", "ok", "challenge"),
        ("https://famishare.jp/", "zendriver_cf", "thin", "dead"),
    ]
    for url, rung, baseline, jev in disagreements:
        assert baseline != to_verdict[jev], f"{url} at {rung} was not a disagreement"
    assert len(disagreements) == 3
