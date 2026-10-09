"""Rung 4: rung 3 with a virtual display in front of it.

Some defences look for a real display before they believe a browser. This rung
is zendriver's fetch with the head taken off and an Xvfb screen behind it, so
nothing about how a page is handled is restated here. What it owns is only what
the measured run varied to get a headed browser: the display.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from . import RungResult, browser_judge, zendriver

# ladder.py:82 `headless=not headed` with headed True
HEADLESS = False
# ladder.py:106 `["Xvfb", disp, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"]`.
# `-nolisten tcp` is a safety property rather than a tuning number: the display
# exists for one local browser and must not be reachable over the network.
XVFB_SCREEN = "1920x1080x24"
XVFB_COMMAND = ("Xvfb", "-screen", "0", XVFB_SCREEN, "-nolisten", "tcp")
# ladder.py:109 `time.sleep(1.5)`, the display's own cold start
XVFB_SETTLE_S = 1.5


def display_for_pid(pid: int) -> str:
    """ladder.py:105 `disp = f":{200 + os.getpid() % 500}"`."""
    return f":{200 + pid % 500}"


def xvfb_command(display: str) -> list[str]:
    """The measured Xvfb invocation with its display slot filled in."""
    return [XVFB_COMMAND[0], display, *XVFB_COMMAND[1:]]


def launch_options() -> dict[str, Any]:
    """Rung 4 is rung 3 with the head taken off, and changes nothing else."""
    return {**zendriver.launch_options(), "headless": HEADLESS}


def fetch(url: str) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise."""
    display = display_for_pid(os.getpid())
    process = subprocess.Popen(
        xvfb_command(display),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # ladder.py:107 `os.environ["DISPLAY"] = disp`: the browser reads the
        # display from the environment, so it has to be set before it starts.
        os.environ["DISPLAY"] = display
        time.sleep(XVFB_SETTLE_S)
        return zendriver.climb(url, launch_options())
    finally:
        process.kill()


def judge(page: dict[str, Any]) -> RungResult:
    return browser_judge(page)