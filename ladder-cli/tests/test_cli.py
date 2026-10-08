"""Handshake, dispatch, and the rung budget."""

from __future__ import annotations

import dataclasses
import io
import json
import sys
import time

from ladder_cli import cli
from ladder_cli.rungs import RungResult, RungVerdict


def sequence(*results: RungResult):
    """A runner that answers in order and records which rungs it was asked for."""
    queue = list(results)
    calls: list[str] = []

    def fake(rung: str, url: str) -> RungResult:
        calls.append(rung)
        return queue.pop(0)

    fake.calls = calls
    return fake


def ok_result(text: str = "body " * 200) -> RungResult:
    return RungResult(RungVerdict.OK, title="An article", text=text, status=200, reason="enough text")


def refused(reason: str = "status 403") -> RungResult:
    return RungResult(RungVerdict.BLOCKED, status=403, reason=reason)


def payload(request) -> dict:
    return dataclasses.asdict(request)


def read_lines(stdout: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_the_ready_line_precedes_every_response_and_declares_the_protocol() -> None:
    stdout = io.StringIO()
    cli.main([], stdin=io.StringIO(""), stdout=stdout)
    assert read_lines(stdout) == [{"ready": True, "protocol": 1}]


def test_a_request_is_answered_with_a_versioned_response(make_request, monkeypatch) -> None:
    runner = sequence(ok_result("clear enough to read"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    stdout = io.StringIO()
    stdin = io.StringIO(json.dumps(payload(make_request())) + "\n")
    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    lines = read_lines(stdout)
    assert lines[0]["ready"] is True
    response = lines[1]
    assert response["protocol"] == 1
    assert response["verdict"] == "ok"
    assert response["rungReached"] == 1
    assert response["text"] == "clear enough to read"
    assert runner.calls == ["http"]


def test_dead_ends_the_climb_before_a_stronger_rung_is_tried(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox", "zendriver_cf"))
    runner = sequence(RungResult(RungVerdict.DEAD, reason="status 404"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "dead"
    assert response.rungReached == 1
    assert runner.calls == ["http"], "a browser cannot revive a page that is gone"


def test_blocked_climbs_until_the_rungs_run_out(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox", "zendriver_cf"))
    runner = sequence(refused(), refused(), ok_result())
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "ok"
    assert response.rungReached == 3
    assert runner.calls == ["http", "camoufox", "zendriver_cf"]


def test_exhausting_every_rung_reports_blocked_not_an_empty_success(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    runner = sequence(refused("status 403"), refused("js shell"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "blocked"
    assert response.rungReached == 2
    assert response.warning == "js shell"


def test_the_rung_ceiling_caps_the_climb(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox", "zendriver_cf"))
    runner = sequence(refused())
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request(rungCeiling=1))
    assert response.verdict == "blocked"
    assert response.rungReached == 1
    assert runner.calls == ["http"]


def test_a_rung_reporting_ok_with_no_text_is_refused_not_propagated(make_request, monkeypatch) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    runner = sequence(ok_result("   "), refused("enough text"))
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    response = cli.dispatch(make_request())
    assert response.verdict == "blocked"
    assert runner.calls == ["http", "camoufox"], "the empty ok must climb, not satisfy the caller"


def test_a_refused_request_is_answered_and_the_loop_carries_on(make_request, monkeypatch) -> None:
    broken = payload(make_request())
    broken["protocol"] = 2
    stdin = io.StringIO(json.dumps(broken) + "\n" + json.dumps(payload(make_request())) + "\n")
    stdout = io.StringIO()
    monkeypatch.setattr(cli, "run_rung_isolated", sequence(ok_result()))

    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    lines = read_lines(stdout)
    assert lines[0]["ready"] is True
    assert lines[1]["verdict"] == "blocked"
    assert "protocol mismatch" in lines[1]["warning"]
    assert lines[2]["verdict"] == "ok", "one bad request must not take the resident child down"


def test_a_rung_that_blows_its_budget_is_killed() -> None:
    started = time.monotonic()
    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=0.5,
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
    )
    elapsed = time.monotonic() - started
    assert elapsed < 20, f"the SIGKILL did not land; waited {elapsed}s"
    assert result.verdict is RungVerdict.BLOCKED
    assert "budget" in result.reason


def test_a_child_record_comes_back_judged_by_the_rung_rules() -> None:
    page = json.dumps({"title": "An article", "text": "body " * 300, "status": 200})
    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=20,
        argv=[sys.executable, "-c", f"print({page!r})"],
    )
    assert result.verdict is RungVerdict.OK
    assert result.status == 200


def test_a_dns_failure_on_the_first_rung_reads_dead() -> None:
    result = cli.run_rung_isolated(
        "http",
        "https://nonexistent.invalid",
        timeout_s=20,
        argv=[sys.executable, "-c", "import sys; print('DNSError: failed to lookup', file=sys.stderr); sys.exit(1)"],
    )
    assert result.verdict is RungVerdict.DEAD
    assert "network" in result.reason


def test_an_unexpected_rung_failure_climbs_and_only_surfaces_when_the_rungs_run_out(
    make_request,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    monkeypatch.setattr(cli, "run_rung_isolated", sequence(RungResult(RungVerdict.ERROR, reason="boom"), RungResult(RungVerdict.ERROR, reason="boom again")))

    stdout = io.StringIO()
    stdin = io.StringIO(json.dumps(payload(make_request())) + "\n")
    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    response = read_lines(stdout)[1]
    assert response["verdict"] == "error"
    assert response["rungReached"] == 2
    assert response["warning"]


def test_an_unexpected_rung_failure_reports_blocked_once_a_page_is_actually_defended(
    make_request,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "RUNGS", ("http", "camoufox"))
    runner = sequence(RungResult(RungVerdict.ERROR, reason="boom"), refused())
    monkeypatch.setattr(cli, "run_rung_isolated", runner)

    stdout = io.StringIO()
    stdin = io.StringIO(json.dumps(payload(make_request())) + "\n")
    assert cli.main([], stdin=stdin, stdout=stdout) == 0

    assert read_lines(stdout)[1]["verdict"] == "blocked"


def test_a_timeout_reads_as_an_error_not_as_the_page_dying() -> None:
    # The spike mapped a timeout to `dead`, which stopped the climb on a blown
    # budget. A budget firing is our machinery, never the page, so it must climb.
    from ladder_cli.rungs import http as rung_http

    assert rung_http.DEAD_NET.search("TimeoutError") is None
    assert rung_http.DEAD_NET.search("timed out") is None
    assert rung_http.DEAD_NET.search("DNSError: failed to lookup")


def test_the_childs_error_line_is_picked_out_of_stderr_noise() -> None:
    # The child prints one `Type: message` line, but it is not the last thing on
    # stderr: a multi-line exception message, or a deprecation notice after it,
    # used to be mistaken for the error.
    stderr = (
        "/usr/lib/ladder_cli/http.py:9: DeprecationWarning: something newer\n"
        "Traceback (most recent call last):\n"
        '  File "x", line 1\n'
        "ValueError: the real reason\nsecond line of the same message\n"
    )
    assert cli._rung_error_line(stderr) == "the real reason"


def test_a_timeout_on_a_rung_is_reported_as_a_budget_not_as_a_network_death() -> None:
    result = cli.run_rung_isolated(
        "http",
        "https://example.com/article",
        timeout_s=20,
        argv=[sys.executable, "-c", "import sys; print('TimeoutError: read timed out', file=sys.stderr); sys.exit(1)"],
    )
    assert result.verdict is RungVerdict.ERROR
    assert "timed out" in result.reason


def test_a_browser_tool_is_not_imported_before_anything_needs_it() -> None:
    # primp is a browser library and rung 1 is the only rung. Importing it at
    # module scope made the resident child owe its ready line before it had
    # touched a browser, so the import moved inside the client that uses it.
    assert "primp" not in sys.modules, "importing the ladder pulled in a browser tool it has not asked for"
