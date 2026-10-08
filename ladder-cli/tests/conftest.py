"""Shared fixtures. Nothing here reaches the network."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ladder_cli.protocol import LadderRequest  # noqa: E402


@pytest.fixture
def make_request():
    """A request carrying the documented defaults, per TDD section 1.2."""

    def build(**overrides: object) -> LadderRequest:
        fields: dict[str, object] = {
            "protocol": 1,
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
