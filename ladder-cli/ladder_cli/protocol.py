"""The contract between serp-axi and ladder-cli.

Both schemas version together: every request declares ``protocol`` and every
response carries it, so a stale installed ladder-cli fails fast with both
numbers named instead of silently misparsing. Request fields are validated on
parse and unknown fields are rejected rather than ignored, because a typo that
is quietly dropped is indistinguishable from a request that ran with defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

PROTOCOL = 1

# A fourth verdict, "error", is not a property of the page: it means the climb
# ran out of rungs because a rung malfunctioned, with no page ever judged. It
# travels beside "blocked" rather than being folded into it, because the caller
# has to act differently: "the page is defended" and "our machinery broke" are
# different sentences, and only one of them is worth retrying.
VERDICTS = ("ok", "dead", "blocked", "error")
TAB_STATES = ("fresh", "same")
COOKIE_STATES = ("cold", "jar")
CACHE_STATES = ("cold", "warm")
FINGERPRINT_STATES = ("rotate", "stable")
RUNG_CEILINGS = (1, 2, 3, 4, 5)

REQUEST_FIELDS = (
    "protocol",
    "url",
    "tabState",
    "cookieState",
    "cacheState",
    "fingerprintState",
    "rungCeiling",
    "profile",
    "jarIn",
    "jarOut",
)


class ProtocolError(ValueError):
    """A request or response that does not satisfy the contract."""


def _one_of(name: str, value: Any, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ProtocolError(f"{name} {value!r} must be one of {', '.join(allowed)}")
    return value


def _optional_path(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError(f"{name} must be a string or null, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class LadderRequest:
    protocol: int
    url: str
    tabState: str
    cookieState: str
    cacheState: str
    fingerprintState: str
    rungCeiling: int
    profile: str | None
    jarIn: str | None
    jarOut: str | None

    @classmethod
    def parse(cls, payload: Any) -> "LadderRequest":
        if not isinstance(payload, dict):
            raise ProtocolError(f"request must be a JSON object, got {type(payload).__name__}")
        unknown = sorted(set(payload) - set(REQUEST_FIELDS))
        if unknown:
            raise ProtocolError(f"unknown field(s): {', '.join(unknown)}")
        missing = sorted(set(REQUEST_FIELDS) - set(payload))
        if missing:
            raise ProtocolError(f"missing field(s): {', '.join(missing)}")

        declared = payload["protocol"]
        if declared != PROTOCOL:
            raise ProtocolError(
                f"protocol mismatch: ladder-cli speaks protocol {PROTOCOL}, "
                f"the request declares {declared!r}; reinstall ladder-cli to match serp-axi"
            )

        url = payload["url"]
        if not isinstance(url, str) or not url.strip():
            raise ProtocolError("url must be a non-empty string")

        ceiling = payload["rungCeiling"]
        if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling not in RUNG_CEILINGS:
            raise ProtocolError(f"rungCeiling {ceiling!r} must be one of 1, 2, 3, 4, 5")

        return cls(
            protocol=PROTOCOL,
            url=url,
            tabState=_one_of("tabState", payload["tabState"], TAB_STATES),
            cookieState=_one_of("cookieState", payload["cookieState"], COOKIE_STATES),
            cacheState=_one_of("cacheState", payload["cacheState"], CACHE_STATES),
            fingerprintState=_one_of("fingerprintState", payload["fingerprintState"], FINGERPRINT_STATES),
            rungCeiling=ceiling,
            profile=_optional_path("profile", payload["profile"]),
            jarIn=_optional_path("jarIn", payload["jarIn"]),
            jarOut=_optional_path("jarOut", payload["jarOut"]),
        )


@dataclass(frozen=True)
class LadderResponse:
    verdict: str
    rungReached: int
    title: str
    text: str
    engines: list[str]
    elapsedMs: int
    warning: str | None
    protocol: int = PROTOCOL

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ProtocolError(f"verdict {self.verdict!r} must be one of {', '.join(VERDICTS)}")
        # An ok verdict with no text is not a small success, it is a bug: the
        # parent rejects the same shape, so asserting here keeps the child from
        # ever producing a response the parent must refuse.
        if self.verdict == "ok" and not self.text.strip():
            raise ProtocolError('verdict "ok" requires non-empty text')

    def encode(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)
