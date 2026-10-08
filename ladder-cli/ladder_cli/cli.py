"""Handshake, NDJSON loop, and dispatch for the resident ladder CLI.

The parent (serp-axi) holds one of these children open across scrapes: we print
a single ready line before reading anything, answer one JSON request per line,
and go quiet when the parent closes stdin. No sockets, no ports, no supervisor
beyond the parent holding our handle.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from typing import IO, Iterable, Sequence

from .protocol import PROTOCOL, LadderRequest, LadderResponse, ProtocolError
from .rungs import RUNGS, RungResult, RungVerdict, fetch, judge, network_verdict

# ladder.py:3 budgets every rung at 90s before SIGKILL. Overridable so the
# budget path can be exercised in a test without waiting a minute and a half.
DEFAULT_RUNG_TIMEOUT_S = 90.0


def rung_timeout_s() -> float:
    raw = os.environ.get("LADDER_RUNG_TIMEOUT_S")
    if raw is None or not raw.strip():
        return DEFAULT_RUNG_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_RUNG_TIMEOUT_S
    return value if value > 0 else DEFAULT_RUNG_TIMEOUT_S


def run_rung_isolated(
    rung: str,
    url: str,
    timeout_s: float | None = None,
    argv: Sequence[str] | None = None,
) -> RungResult:
    """Run one rung as a subprocess under a hard time budget.

    A subprocess is what makes the budget enforceable: it is the thing that can
    be SIGKILLed. The child is started in its own session so the kill reaches
    whatever it spawned underneath it, matching ladder.py:189.
    """
    budget = rung_timeout_s() if timeout_s is None else timeout_s
    command = list(argv) if argv is not None else [sys.executable, "-m", "ladder_cli", "--rung", rung, url]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = process.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.communicate()
        return RungResult(RungVerdict.BLOCKED, reason=f"rung {rung} exceeded its {budget:g}s budget")

    lines = [line for line in (out or "").splitlines() if line.startswith("{")]
    if lines:
        try:
            page = json.loads(lines[-1])
        except json.JSONDecodeError:
            page = None
        if isinstance(page, dict) and "text" in page:
            return judge(rung, page)

    message = ((err or "").strip().splitlines() or ["?"])[-1][:160]
    verdict = network_verdict(message)
    if verdict is RungVerdict.DEAD:
        return RungResult(verdict, reason=f"network: {message}")
    return RungResult(verdict, reason=message)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _response(verdict: str, rung_reached: int, result: RungResult, started: float) -> LadderResponse:
    return LadderResponse(
        verdict=verdict,
        rungReached=rung_reached,
        title=result.title,
        text=result.text,
        engines=[],
        elapsedMs=_elapsed_ms(started),
        warning=result.reason or None,
    )


def dispatch(request: LadderRequest, *, runner=None) -> LadderResponse:
    """Climb the ladder for one request.

    Two verdicts end the climb early and the rest keep going: ``ok`` because the
    page arrived, ``dead`` because a stronger rung cannot revive a domain that
    does not resolve or a page that says it is parked (ladder.py:196). Blocked,
    a blown budget, and a rung that malfunctioned all mean try the next one.
    Exhausting the rungs reports ``blocked``, never an empty success.

    The runner defaults by lookup rather than by argument value so a test can
    replace ``run_rung_isolated`` on this module.
    """
    if runner is None:
        runner = run_rung_isolated
    started = time.monotonic()
    rung_reached = 0
    last: RungResult | None = None

    for index, rung in enumerate(RUNGS[: request.rungCeiling]):
        rung_reached = index + 1
        last = runner(rung, request.url)
        if last.verdict is RungVerdict.OK and not last.text.strip():
            # Asserted by both sides; converting rather than crashing keeps the
            # resident child alive across a bad response.
            last = RungResult(
                RungVerdict.BLOCKED,
                last.title,
                last.text,
                last.status,
                "rung reported ok with no text",
            )
        if last.verdict is RungVerdict.OK:
            return _response("ok", rung_reached, last, started)
        if last.verdict is RungVerdict.DEAD:
            return _response("dead", rung_reached, last, started)

    if last is None:
        return LadderResponse(
            verdict="blocked",
            rungReached=0,
            title="",
            text="",
            engines=[],
            elapsedMs=_elapsed_ms(started),
            warning=f"no rungs available at a ceiling of {request.rungCeiling}",
        )
    return _response("blocked", rung_reached, last, started)


def _run_rung_child(rung: str, url: str, stdout: IO[str], stderr: IO[str]) -> int:
    try:
        page = fetch(rung, url)
    except Exception as error:  # noqa: BLE001 - the parent maps the message, not the type
        print(f"{type(error).__name__}: {error}", file=stderr, flush=True)
        return 1
    stdout.write(json.dumps(page, ensure_ascii=False) + "\n")
    stdout.flush()
    return 0


def _write(stdout: IO[str], payload: str) -> None:
    stdout.write(payload + "\n")
    stdout.flush()


def _refusal(reason: str) -> LadderResponse:
    return LadderResponse(
        verdict="blocked",
        rungReached=0,
        title="",
        text="",
        engines=[],
        elapsedMs=0,
        warning=reason,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: Iterable[str] | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    if len(args) >= 3 and args[0] == "--rung":
        return _run_rung_child(args[1], args[2], stdout, stderr)

    # Readiness is announced before the first read, so no caller ever sleeps a
    # fixed interval and hopes. Anything the parent writes before this line is
    # not possible, since we have not read anything yet.
    _write(stdout, json.dumps({"ready": True, "protocol": PROTOCOL}))

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = dispatch(LadderRequest.parse(json.loads(line)))
        except ProtocolError as error:
            response = _refusal(str(error))
        except Exception as error:  # noqa: BLE001 - a failed request, never a hang
            response = _refusal(f"{type(error).__name__}: {error}")
        _write(stdout, response.encode())
    return 0
