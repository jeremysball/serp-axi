"""Cookie jars, allowlist-filtered.

A jar exists because Chrome writes cookies lazily and ``stop()`` kills it first
(solver_probe.py:85), so the cookies a solve earned have to be carried out of the
browser by something. The filter is the point of the module: a profile persists
across requests and therefore holds every site's cookies, so only the target's
own defence cookies are allowed out of it (solver_probe.py:28, H3).
"""

from __future__ import annotations

from pathlib import Path

from ladder_cli.state import jars


def cookie(name: str, domain: str, value: str = "v") -> jars.Cookie:
    return jars.Cookie(name=name, domain=domain, value=value)


def test_only_the_defence_cookies_the_spike_kept_are_kept() -> None:
    # solver_probe.py:27 `KEEP = ("cf_clearance", "_px3", "_pxhd", "datadome")`
    assert jars.KEEP == ("cf_clearance", "_px3", "_pxhd", "datadome")
    for name in jars.KEEP:
        assert jars.keeps(name, ".example.com", "https://example.com/"), name
    for name in ("sessionid", "PHPSESSID", "_ga", "cf_bm"):
        assert not jars.keeps(name, ".example.com", "https://example.com/"), name


def test_another_sites_cookie_does_not_travel_with_the_target() -> None:
    """solver_probe.py:28 (H3): the persistent profile holds every site's cookies."""
    assert not jars.keeps("cf_clearance", ".other.com", "https://example.com/")
    kept = jars.filter_cookies(
        [cookie("cf_clearance", ".example.com"), cookie("cf_clearance", ".other.com")],
        "https://example.com/",
    )
    assert [c.name for c in kept] == ["cf_clearance"]
    assert kept[0].domain == ".example.com"


def test_a_subdomain_of_the_target_is_the_target() -> None:
    assert jars.keeps("cf_clearance", ".sub.example.com", "https://example.com/")
    assert jars.keeps("cf_clearance", "shop.example.com", "https://shop.example.com/")


def test_the_domain_match_stops_at_a_label_boundary() -> None:
    """A plain suffix test would let a lookalike domain smuggle its cookies in.

    ``"evil-example.com".endswith("example.com")`` is true, so the spike's own
    ``endswith`` filter keeps a cookie scoped to a domain that merely *ends* with
    the target's name. This is one of two places where porting measured
    behaviour differs from porting measured constants: the allowlist and the
    base-domain scope are measured, this predicate is the part that got the
    scope wrong, and it is corrected here with the reason stated.
    """
    assert not jars.keeps("cf_clearance", ".evil-example.com", "https://example.com/")
    assert not jars.keeps("cf_clearance", "notexample.com", "https://example.com/")
    assert not jars.keeps("cf_clearance", ".example.com.evil.test", "https://example.com/")
    assert jars.keeps("cf_clearance", ".example.com", "https://example.com/")


def test_a_jar_round_trips_so_the_caller_can_find_out_whether_replay_helps(tmp_path: Path) -> None:
    """jarIn and jarOut are separate fields precisely so a caller can learn this.

    04-tdd 1.8 leaves open "whether anything rescues jar replay (want 4)" and
    says the separate fields are what let a caller find out. A round-trip that
    loses a cookie would answer that question wrongly.
    """
    out = [
        cookie("cf_clearance", ".example.com", "cleared"),
        cookie("datadome", ".example.com", "dd"),
    ]
    path = jars.path_for(tmp_path, "warm")
    written = jars.save(path, out, "https://example.com/")

    assert written == 2
    assert jars.load(path, "https://example.com/") == out


def test_loading_a_jar_re_applies_the_filter_rather_than_trusting_the_file(tmp_path: Path) -> None:
    """A jar is data on disk; anything can widen one by hand."""
    import json

    path = jars.path_for(tmp_path, "warm")
    jars.save(path, [cookie("cf_clearance", ".example.com", "ok")], "https://example.com/")

    widened = json.loads(path.read_text())
    widened["cookies"].append({"name": "sessionid", "domain": ".example.com", "value": "x"})
    path.write_text(json.dumps(widened))

    assert [c.name for c in jars.load(path, "https://example.com/")] == ["cf_clearance"]


def test_a_jar_written_for_one_site_is_not_replayed_onto_another(tmp_path: Path) -> None:
    path = jars.path_for(tmp_path, "warm")
    jars.save(path, [cookie("cf_clearance", ".example.com", "ok")], "https://example.com/")

    assert jars.load(path, "https://other.com/") == [], "the filter runs at load time too"


def test_the_jar_path_is_named_after_the_profile() -> None:
    # solver_probe.py:86 `os.path.join(PROFILES, name + ".cookies.dat")`
    assert jars.path_for(Path("/p"), "zendriver_cf") == Path("/p") / "zendriver_cf.cookies.dat"


def test_a_killed_browser_leaves_no_lock_behind_for_the_next_launch(tmp_path: Path) -> None:
    """solver_probe.py:35 (H4): a SIGKILLed browser stalls the next one on a stale lock."""
    # solver_probe.py:35-41, the five names it unlinks
    assert jars.PROFILE_LOCKS == (
        "lock",
        ".parentlock",
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
    )

    profile = tmp_path / "locktest"
    profile.mkdir()
    for name in jars.PROFILE_LOCKS:
        (profile / name).write_text("stale")

    assert jars.clear_locks(profile) == 5
    assert [p.name for p in profile.iterdir()] == []
    assert jars.clear_locks(profile) == 0, "clearing twice is not an error"


def test_replay_alone_is_still_expected_to_stay_blocked() -> None:
    """The measured outcome of q3_restart, encoded so the gap stays visible.

    The run loaded a jar into a fresh browser and replayed the same URL 3/3
    times; every one of them came back a challenge page. Want 4 ("whether
    anything rescues jar replay") is therefore still unmet, and this module is
    deliberately not the thing that claims otherwise: it moves the cookies and
    says nothing about whether the browser will honour them.
    """
    assert jars.JAR_REPLAY_EXPECTATION == "blocked"
    assert jars.JAR_REPLAY_RESCUES is False


def test_a_multi_label_public_suffix_is_not_treated_as_the_base_domain() -> None:
    """co.uk is a public suffix, not a site. Taking two labels makes it the base.

    The measured filter scoped a cookie to `base_domain(host)`, and taking the
    last two labels turns `www.bbc.co.uk` into `co.uk`. Every defence cookie
    scoped to any `.co.uk` sibling then passes the filter and travels with the
    fetch, which is the same class of bug as the lookalike domain one label
    further out.
    """
    assert jars.base_domain("www.bbc.co.uk") == "bbc.co.uk"
    assert jars.base_domain("news.bbc.co.uk") == "bbc.co.uk"

    # A sibling under the same public suffix is a different site.
    assert not jars.keeps("cf_clearance", ".other.co.uk", "https://www.bbc.co.uk/")
    assert not jars.keeps("cf_clearance", ".co.uk", "https://www.bbc.co.uk/")

    # The target's own cookies still travel.
    assert jars.keeps("cf_clearance", ".bbc.co.uk", "https://www.bbc.co.uk/")
