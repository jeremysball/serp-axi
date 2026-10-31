"""The two-sided schema contract from TDD section 2.3."""

from __future__ import annotations

import json

import pytest

from ladder_cli.protocol import LadderRequest, LadderResponse, ProtocolError


def valid_payload() -> dict[str, object]:
    return {
        "protocol": 3,
        "url": "https://example.com/article",
        "tabState": "fresh",
        "cookieState": "cold",
        "cacheState": "cold",
        "fingerprintState": "rotate",
        "rungCeiling": 5,
        "profile": None,
        "jarIn": None,
        "jarOut": None,
        "httpJarIn": None,
        "httpJarOut": None,
    }


def test_a_request_with_the_documented_defaults_parses() -> None:
    request = LadderRequest.parse(valid_payload())
    assert request.url == "https://example.com/article"
    assert request.tabState == "fresh"
    assert request.rungCeiling == 5
    assert request.profile is None


@pytest.mark.parametrize("field", ["jarIn", "jarOut", "httpJarIn", "httpJarOut"])
def test_each_jar_path_is_nullable_but_not_an_untyped_value(field):
    payload = valid_payload()
    payload[field] = "session.path"
    assert getattr(LadderRequest.parse(payload), field) == "session.path"
    payload[field] = 42
    with pytest.raises(ProtocolError, match=field + " must be a string or null"):
        LadderRequest.parse(payload)


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
    payload["protocol"] = 1
    with pytest.raises(ProtocolError, match=r"speaks protocol 3.*declares 1"):
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
    assert decoded["protocol"] == 3
    assert decoded["verdict"] == "blocked"
    assert decoded["warning"] == "status 403"


def test_links_round_trip_through_the_response() -> None:
    response = LadderResponse(
        verdict="ok",
        rungReached=1,
        title="Example",
        text="body",
        engines=[],
        elapsedMs=1,
        warning=None,
        links=[{"url": "https://example.com/a", "text": "A"}],
    )
    decoded = json.loads(response.encode())
    assert decoded["links"] == [{"url": "https://example.com/a", "text": "A"}]


@pytest.mark.parametrize(
    ("link", "message"),
    [
        ("https://example.com/a", "must be an object"),
        ({"url": "", "text": ""}, "url .* must be a non-empty string"),
        ({"url": "https://example.com/a", "text": 1}, "text .* must be a string"),
    ],
)
def test_a_malformed_link_is_rejected(link: object, message: str) -> None:
    with pytest.raises(ProtocolError, match=message):
        LadderResponse(
            verdict="ok",
            rungReached=1,
            title="",
            text="body",
            engines=[],
            elapsedMs=1,
            warning=None,
            links=[link],
        )
