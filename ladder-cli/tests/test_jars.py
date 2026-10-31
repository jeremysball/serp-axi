"""Cookie jars, allowlist-filtered.

A jar exists because Chrome writes cookies lazily and ``stop()`` kills it first
(solver_probe.py:85), so the cookies a solve earned have to be carried out of the
browser by something. The filter is the point of the module: a profile persists
across requests and therefore holds every site's cookies, so only the target's
own defence cookies are allowed out of it (solver_probe.py:28, H3).
"""

from __future__ import annotations

from pathlib import Path
import os
import socket
import subprocess
import sys

import pytest

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


def test_a_replayed_cookie_keeps_its_path_and_http_only_flag(tmp_path: Path) -> None:
    """A `cf_clearance` replayed without its path is not the cookie earned.

    zendriver's `CookieParam` carries both, so a jar that dropped them would
    still load and still be wrong in a way no other test would see.
    """
    earned = jars.Cookie(
        name="cf_clearance",
        domain=".example.com",
        value="cleared",
        secure=True,
        same_site="Lax",
        path="/account",
        http_only=True,
    )
    path = jars.path_for(tmp_path, "warm")
    jars.save(path, [earned], "https://example.com/")

    assert jars.load(path, "https://example.com/") == [earned]


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


def test_the_jar_path_is_named_after_the_profile_and_says_json() -> None:
    """The measured run reused zendriver's `.cookies.dat`, which is a pickle.

    This module writes JSON, so it takes a JSON name: two formats must not
    claim one path, and a jar a human opens should say which format it is.
    """
    assert jars.path_for(Path("/p"), "zendriver_cf") == Path("/p") / "zendriver_cf.cookies.json"


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
    (profile / "SingletonLock").unlink()
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    (profile / "SingletonLock").symlink_to(f"{socket.gethostname()}-{child.pid}")

    assert jars.clear_locks(profile) == 5
    assert [p.name for p in profile.iterdir()] == []
    assert jars.clear_locks(profile) == 0, "clearing twice is not an error"


@pytest.mark.parametrize("suffix", ["co.il", "com.ua", "co.id", "com.my", "github.io"])
def test_cookie_scope_does_not_cross_an_unlisted_public_or_private_suffix(suffix: str) -> None:
    url = f"https://www.example.{suffix}/"
    assert jars.keeps("cf_clearance", f".example.{suffix}", url)
    assert not jars.keeps("cf_clearance", f".other.{suffix}", url)
    assert not jars.keeps("cf_clearance", f".{suffix}", url)


def test_unknown_suffixes_stay_host_scoped_without_network_access(monkeypatch):
    def network_attempt(*args, **kwargs):
        pytest.fail("cookie scoping must use bundled suffix data without a network refresh")

    monkeypatch.setattr(socket.socket, "connect", network_attempt)
    jars._suffixes.cache_clear()
    url = "https://www.example.unknown-suffix/"
    assert jars.base_domain("www.example.co.uk") == "example.co.uk"
    assert jars.keeps("cf_clearance", ".www.example.unknown-suffix", url)
    assert not jars.keeps("cf_clearance", ".example.unknown-suffix", url)


@pytest.mark.parametrize("owner", ["live", "foreign", "unknown"])
def test_cleanup_refuses_a_lock_without_proof_its_owner_is_dead(tmp_path: Path, owner: str) -> None:
    stale = tmp_path / "stale"
    stale.mkdir()
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    (stale / "SingletonLock").symlink_to(f"{socket.gethostname()}-{child.pid}")
    assert jars.clear_locks(stale) == 1

    protected = tmp_path / "protected"
    protected.mkdir()
    lock = protected / "SingletonLock"
    if owner == "unknown":
        lock.write_text("unrecognized lock")
    else:
        host = socket.gethostname() if owner == "live" else "another-host"
        lock.symlink_to(f"{host}-{os.getpid()}")
    with pytest.raises(RuntimeError, match="profile.*lock"):
        jars.clear_locks(protected)
    assert lock.is_symlink() or lock.is_file()


def test_cleanup_distinguishes_a_zombie_owner_from_a_running_owner(tmp_path: Path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    lock = tmp_path / "SingletonLock"
    try:
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
        assert Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
        os.kill(child.pid, 0)
        lock.symlink_to(f"{socket.gethostname()}-{child.pid}")
        assert jars.clear_locks(tmp_path) == 1
        lock.symlink_to(f"{socket.gethostname()}-{os.getpid()}")
        with pytest.raises(RuntimeError, match="still running"):
            jars.clear_locks(tmp_path)
        assert lock.is_symlink()
    finally:
        child.wait(timeout=10)


def test_corrupt_jar_is_not_silently_treated_as_a_cold_start(tmp_path: Path) -> None:
    path = tmp_path / "cookies.json"
    jars.save(path, [cookie("cf_clearance", ".example.com")], "https://example.com/")
    assert len(jars.load(path, "https://example.com/")) == 1
    for contents in ('{"cookies":', '{"cookies": 1}', '[]'):
        path.write_text(contents)
        with pytest.raises(ValueError):
            jars.load(path, "https://example.com/")


def test_non_missing_jar_read_error_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "directory.json"
    path.mkdir()
    with pytest.raises(OSError):
        jars.load(path, "https://example.com/")


@pytest.mark.parametrize("record", [
    None, 42, [], {},
    {"name": "cf_clearance", "domain": ".example.com"},
    {"name": "cf_clearance", "value": "ok"},
    {"domain": ".example.com", "value": "ok"},
    {"name": 42, "domain": ".example.com", "value": "ok"},
    {"name": "cf_clearance", "domain": ".example.com", "value": None},
    {"name": "cf_clearance", "domain": ".example.com", "value": "ok", "secure": "false"},
    {"name": "cf_clearance", "domain": ".example.com", "value": "ok", "expires": "tomorrow"},
])
def test_malformed_cookie_records_are_not_silently_dropped_or_coerced(tmp_path, record):
    import json

    path = tmp_path / "cookies.json"
    jars.save(path, [cookie("cf_clearance", ".example.com", "ok")], "https://example.com/")
    assert jars.load(path, "https://example.com/") == [cookie("cf_clearance", ".example.com", "ok")]
    path.write_text(json.dumps({"cookies": [record]}))

    with pytest.raises(ValueError, match="invalid cookie jar"):
        jars.load(path, "https://example.com/")


def test_failed_jar_write_preserves_the_existing_jar(tmp_path):
    path = tmp_path / "cookies.json"
    jars.save(path, [cookie("cf_clearance", ".example.com", "earned")], "https://example.com/")
    original = path.read_bytes()
    result = subprocess.run([
        sys.executable, "-c",
        "import resource, signal, sys\n"
        "from pathlib import Path\n"
        "from ladder_cli.state import jars\n"
        "signal.signal(signal.SIGXFSZ, signal.SIG_IGN)\n"
        "resource.setrlimit(resource.RLIMIT_FSIZE, (512, 512))\n"
        "try:\n"
        "    jars.save(Path(sys.argv[1]), [jars.Cookie('cf_clearance', '.example.com', 'x' * 4096)], 'https://example.com/')\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('file-size limit must reject the oversized jar')\n",
        str(path),
    ], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert path.read_bytes() == original
    assert jars.load(path, "https://example.com/") == [cookie("cf_clearance", ".example.com", "earned")]


def test_non_missing_lock_cleanup_error_is_reported(tmp_path: Path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    (tmp_path / "SingletonLock").symlink_to(f"{socket.gethostname()}-{child.pid}")
    (tmp_path / "SingletonCookie").mkdir()
    with pytest.raises(OSError):
        jars.clear_locks(tmp_path)
    assert (tmp_path / "SingletonLock").is_symlink(), "failed cleanup must retain the owner proof for retry"
    (tmp_path / "SingletonCookie").rmdir()
    assert jars.clear_locks(tmp_path) == 1


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


def test_a_url_the_filter_cannot_scope_is_rejected_rather_than_crashed() -> None:
    """LadderRequest.parse accepts any non-empty string, so anything can arrive.

    keeps() took the host with `url.split("/")[2]`, which raises IndexError on a
    scheme-less URL and keeps a `:port` inside the scope it computes. A filter
    that cannot tell what site it is scoping to must refuse the cookie, not
    crash, and must not silently widen or narrow the match either.
    """
    # No scheme: the host is not the third slash-separated field.
    assert jars.keeps("cf_clearance", ".example.com", "example.com") is False
    assert jars.keeps("cf_clearance", ".example.com", "") is False

    # A port is not part of the scope and must not defeat a legitimate match.
    assert jars.keeps("cf_clearance", ".example.com", "https://example.com:8443/") is True
    assert jars.keeps("cf_clearance", ".example.com", "https://user:pass@example.com/") is True


@pytest.mark.parametrize("url", ["http://[::1", "http://[z::1]/"])
def test_malformed_bracketed_hosts_fail_closed(url):
    assert jars.keeps("cf_clearance", ".example.com", "https://example.com/")
    try:
        kept = jars.keeps("cf_clearance", ".example.com", url)
    except ValueError as error:
        pytest.fail(f"an unscopable URL must refuse cookies, not raise: {error}")
    assert kept is False


def test_atomic_jar_save_preserves_a_symlink_and_updates_its_target(tmp_path):
    target = tmp_path / "target.json"
    path = tmp_path / "jar.json"
    path.symlink_to(target.name)
    expected = [cookie("cf_clearance", ".example.com", "updated")]

    assert jars.save(path, expected, "https://example.com/") == 1
    assert path.is_symlink()
    assert jars.load(target, "https://example.com/") == expected


@pytest.mark.parametrize("domain,url", [
    (".xn--bcher-kva.de", "https://b\u00fccher.de/"),
    (".b\u00fccher.de", "https://xn--bcher-kva.de/"),
    (".xn--fa-hia.de", "https://fa\u00df.de/"),
])
def test_idn_cookie_and_url_representations_share_the_same_scope(domain, url):
    assert jars.keeps("cf_clearance", domain, url)
    assert not jars.keeps("cf_clearance", ".unrelated.de", url)
