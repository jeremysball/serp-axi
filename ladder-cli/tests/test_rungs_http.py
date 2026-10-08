"""Rung 1 verdict rules against recorded page shapes.

Fixtures here are hand-written to the shapes the measured run actually saw, so
the thresholds stay pinned to evidence rather than to whatever a fetch happens
to return today. Nothing in this file touches the network.
"""

from __future__ import annotations

import pytest

from ladder_cli.rungs import RungVerdict, http


def page(title: str, text: str, status: int | None = 200) -> dict:
    return {"title": title, "text": text, "status": status}


def article(length: int = 900) -> str:
    return "An article opening. " + ("content " * (length // 8))


def test_real_content_passes() -> None:
    result = http.judge(page("An article", article()))
    assert result.verdict is RungVerdict.OK
    assert result.status == 200


def test_a_gone_page_is_dead_and_a_defended_page_is_blocked() -> None:
    gone = http.judge(page("Not found", "nope", status=404))
    assert gone.verdict is RungVerdict.DEAD, "404 must not climb: no browser revives a deleted page"

    defended = http.judge(page("Access denied", "nope", status=403))
    assert defended.verdict is RungVerdict.BLOCKED, "403 may clear in a stronger rung"


@pytest.mark.parametrize("status", [521, 522, 523, 525, 526, 530])
def test_a_dead_origin_is_dead_not_blocked(status: int) -> None:
    assert http.judge(page("Origin down", article(), status=status)).verdict is RungVerdict.DEAD


def test_a_bot_check_reads_blocked_even_when_the_page_is_short() -> None:
    text = "Just a moment... checking your browser before you continue."
    result = http.judge(page("Attention Required", text))
    assert result.verdict is RungVerdict.BLOCKED
    assert result.reason == "challenge marker"


def test_content_thinner_than_the_rung_one_floor_climbs() -> None:
    result = http.judge(page("Home", "Home and little else."))
    assert result.verdict is RungVerdict.BLOCKED
    assert "under rung-1 floor" in result.reason


def test_a_client_side_shell_is_not_a_successful_fetch() -> None:
    text = "Loading... " + ("nav " * 120)
    result = http.judge(page("App", text))
    assert result.verdict is RungVerdict.BLOCKED
    assert result.reason == "js shell (loading marker)"


def test_page_text_short_of_the_thin_baseline_climbs() -> None:
    result = http.judge(page("Short", "A tidy page, but only five hundred characters of actual prose. " + "x" * 440))
    assert result.verdict is RungVerdict.BLOCKED
    assert "chars" in result.reason


def test_a_site_api_answer_passes_without_the_html_floor() -> None:
    result = http.judge(page("api", "a thread of posts", status=200))
    assert result.verdict is RungVerdict.OK
    assert result.reason == "site api"


def test_reddit_comment_urls_prefer_the_site_api() -> None:
    url = "https://www.reddit.com/r/python/comments/abc123/some_thread/"
    assert http.api_url(url) == "https://www.reddit.com/r/python/comments/abc123/some_thread.json?limit=200"


def test_hacker_news_item_urls_prefer_the_site_api() -> None:
    assert http.api_url("https://news.ycombinator.com/item?id=12345") == "https://hn.algolia.com/api/v1/items/12345"


def test_ordinary_urls_have_no_api_form() -> None:
    assert http.api_url("https://example.com/article") is None


def test_flatten_api_gathers_readable_bodies_recursively() -> None:
    payload = {
        "title": "thread",
        "children": [
            {"data": {"author": "ann", "score": 12, "body": "hello <b>world</b>"}},
            {"data": {"author": "bob", "points": 3, "selftext": "second post"}},
        ],
    }
    flat = http.flatten_api("https://example.com", payload)
    assert "[ann 12] hello world" in flat, "stripping a tag must not leave a double space behind"
    assert "[bob 3] second post" in flat


def test_flatten_api_does_not_render_missing_metadata_as_the_word_none() -> None:
    flat = http.flatten_api("https://example.com", {"title": "a thread with no author"})
    assert flat == "a thread with no author"
    assert "None" not in flat
