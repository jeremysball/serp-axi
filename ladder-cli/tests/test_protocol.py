"""The two-sided schema contract from TDD section 2.3."""

from __future__ import annotations

import json

import pytest

from ladder_cli.protocol import LadderRequest, LadderResponse, ProtocolError


def valid_payload() -> dict[str, object]:
    return {
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


def test_a_request_with_the_documented_defaults_parses() -> None:
    request = LadderRequest.parse(valid_payload())
    assert request.url == "https://example.com/article"
    assert request.tabState == "fresh"
    assert request.rungCeiling == 5
    assert request.profile is None


def test_a_field_the_parent_never_sends_is_rejected_not_ignored() -> None:
    payload = valid_payload()
    payload["tabSate"] = "same"
    with pytest.raises(ProtocolError, match=r"unknown field\(s\): tabSate"):
        LadderRequest.parse(payload)


def test_a_missing_field_is_rejected() -> None:
    payload = valid_payload()
    del payload["rungCeiling"]
    with pytest.raises(ProtocolError, match=r"missing field\(s\): rungCeiling"):
        LadderRequest.parse(payload)


def test_a_protocol_mismatch_names_both_sides() -> None:
    payload = valid_payload()
    payload["protocol"] = 2
    with pytest.raises(ProtocolError, match=r"speaks protocol 1.*declares 2"):
        LadderRequest.parse(payload)


@pytest.mark.parametrize(
    ("field", "value", "allowed"),
    [
        ("tabState", "sideways", "fresh, same"),
        ("cookieState", "warm", "cold, jar"),
        ("cacheState", "jar", "cold, warm"),
        ("fingerprintState", "stable-ish", "rotate, stable"),
    ],
)
def test_an_axis_outside_its_vocabulary_is_rejected(field: str, value: str, allowed: str) -> None:
    payload = valid_payload()
    payload[field] = value
    with pytest.raises(ProtocolError, match=f"{field} {value!r} must be one of {allowed}"):
        LadderRequest.parse(payload)


@pytest.mark.parametrize("ceiling", [0, 6, 5.0, "5", True])
def test_a_rung_ceiling_outside_1_to_5_is_rejected(ceiling: object) -> None:
    payload = valid_payload()
    payload["rungCeiling"] = ceiling
    with pytest.raises(ProtocolError, match="rungCeiling"):
        LadderRequest.parse(payload)


def test_a_non_object_request_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="must be a JSON object"):
        LadderRequest.parse(["https://example.com"])


def test_a_response_cannot_claim_ok_with_no_text() -> None:
    with pytest.raises(ProtocolError, match=r'verdict "ok" requires non-empty text'):
        LadderResponse(
            verdict="ok",
            rungReached=1,
            title="",
            text="   ",
            engines=[],
            elapsedMs=1,
            warning=None,
        )


def test_a_refusal_may_carry_empty_text() -> None:
    response = LadderResponse(
        verdict="blocked",
        rungReached=1,
        title="",
        text="",
        engines=[],
        elapsedMs=1,
        warning="status 403",
    )
    decoded = json.loads(response.encode())
    assert decoded["protocol"] == 1
    assert decoded["verdict"] == "blocked"
    assert decoded["warning"] == "status 403"
