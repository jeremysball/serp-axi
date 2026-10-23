"""Shared fixtures. Nothing here reaches the network."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ladder_cli.protocol import LadderRequest  # noqa: E402


@pytest.fixture
def make_request():
    """A request carrying the documented defaults, per TDD section 1.2."""

    def build(**overrides: object) -> LadderRequest:
        fields: dict[str, object] = {
            "protocol": 2,
            "url": "https://example.com/article",
            "tabState": "fresh",
            "cookieState": "cold",
            "cacheState": "cold",
            "fingerprintState": "rotate",
            "rungCeiling": 5,
            "profile": None,
            "jarIn": None,
            "jarOut": None,
        }
        fields.update(overrides)
        return LadderRequest.parse(fields)

    return build


class Recorder(list):
    """A call log that reads as a sequence, so a fixture asserts what a rung asked."""

    def __call__(self, entry):
        self.append(entry)
        return entry

    def names(self) -> list[str]:
        return [entry[0] for entry in self]


def inject_module(monkeypatch, name: str, module):
    """Bind a fake library where the rung's deferred import will find it.

    The browser rungs import their tool inside ``fetch`` rather than at module
    scope, so a test replaces it the same way. One helper owns the injection
    because every browser-rung test needed it, and a second copy of a
    monkeypatch is how a rung silently stops being tested at all.
    """
    monkeypatch.setitem(sys.modules, name, module)
    parent, _, child = name.rpartition(".")
    if parent:
        monkeypatch.setitem(sys.modules, parent, types.SimpleNamespace(**{child: module}))
