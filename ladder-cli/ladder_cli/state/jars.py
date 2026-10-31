"""Cookie jars: the allowlist-filtered way to carry a solve out of a browser.

A jar exists because Chrome writes cookies lazily and ``stop()`` kills the
browser first (solver_probe.py:85), so the cookies a solve earned are gone
unless something carries them out. The filter is what makes that safe: a warmed
profile is reused for the CLI's whole life and therefore holds every site's
cookies, so only the target's own defence cookies may leave it
(solver_probe.py:28, H3).

What this module does not do is say whether replay works. The measured run
loaded a jar into a fresh browser 3/3 times and every one came back a challenge
page, so ``JAR_REPLAY_RESCUES`` is ``False`` and the separate ``jarIn`` and
``jarOut`` request fields exist so a caller can find out for itself
(04-tdd 1.8, want 4).

The file is JSON; ``path_for`` suggests ``<name>.cookies.json``. The measured run reused
``<name>.cookies.dat``, which is the path zendriver's own cookie file defaults
to and that file is a pickle (``CookieJar.save``); two formats must not claim
one path. Explicit request paths are used unchanged, so callers must not point
JSON jar output at an existing browser pickle file.
"""

from __future__ import annotations

import json
import math
import os
import socket
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from urllib.parse import urlparse

# solver_probe.py:27 `KEEP = ("cf_clearance", "_px3", "_pxhd", "datadome")`.
# The four defence cookies the measured run carried; anything else is a
# browsing cookie and has no business travelling with the fetch.
KEEP: tuple[str, ...] = ("cf_clearance", "_px3", "_pxhd", "datadome")

# solver_probe.py:35 (H4): "a SIGKILLed browser leaves its profile lock behind;
# the next launch stalls on it".
PROFILE_LOCKS: tuple[str, ...] = (
    "lock",
    ".parentlock",
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
)

# q3_restart: replaying a jar into a fresh browser was blocked 3/3.
JAR_REPLAY_EXPECTATION = "blocked"
JAR_REPLAY_RESCUES = False


@dataclass(frozen=True)
class Cookie:
    """The fields the jar round-trips.

    ``domain`` is kept as the browser wrote it, leading dot included, because
    the scoping predicate below is the thing that decides what a domain means.
    ``path`` and ``http_only`` are carried because replaying a ``cf_clearance``
    cookie without its path or its HttpOnly flag is not the cookie that was
    earned.
    """

    name: str
    domain: str
    value: str
    expires: float | None = None
    secure: bool = False
    same_site: str | None = None
    path: str = "/"
    http_only: bool = False


@cache
def _suffixes():
    from tldextract import TLDExtract

    return TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)


def _ascii_host(host: str) -> str:
    host = host.lower().rstrip(".")
    if host.isascii():
        return host
    import idna

    try:
        return idna.encode(host, uts46=True).decode("ascii")
    except idna.IDNAError:
        return ""


def base_domain(host: str) -> str:
    """Use the bundled public/private suffix snapshot; unknown suffixes stay host-scoped."""
    host = _ascii_host(host)
    extracted = _suffixes()(host)
    if not extracted.suffix:
        return host
    return extracted.top_domain_under_public_suffix


def _host_of(url: str) -> str | None:
    """The host a URL scopes to, or None when it cannot be determined.

    urllib.parse returns the hostname with the port and userinfo already
    stripped, which is exactly the thing the scope is computed over. The
    measured code took `url.split("/")[2]`, which raises IndexError on a
    scheme-less URL and leaves `:8443` inside the scope so an explicit port
    defeats a legitimate match. LadderRequest.parse accepts any non-empty
    string, so refusing what cannot be scoped is the only safe answer: a filter
    that cannot say what site it is guarding must not say yes.
    """
    if "://" not in url:
        return None
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def keeps(name: str, domain: str, url: str) -> bool:
    """Whether one cookie may travel with a fetch for ``url``.

    solver_probe.py:31, with two corrections and the reason recorded: the spike
    filtered on ``domain.lstrip(".").endswith(base)``, and ``"evil-example.com"
    .endswith("example.com")`` is true, so a cookie scoped to a lookalike domain
    passed the filter. The match has to stop at a label boundary. And the host
    came from a raw string split that crashed on a URL without a scheme.
    """
    if name not in KEEP:
        return False
    host = _host_of(url)
    if host is None:
        return False
    base = base_domain(host)
    if not base:
        return False
    scope = _ascii_host(domain.lstrip("."))
    return scope == base or scope.endswith("." + base)


def filter_cookies(cookies: Iterable[Cookie], url: str) -> list[Cookie]:
    """The cookies that survive the allowlist and the base-domain scope.

    Returned in a stable order so two saves of the same state are byte-equal and
    a jar diff means the cookies changed rather than the enumeration order.
    """
    return sorted(
        (cookie for cookie in cookies if keeps(cookie.name, cookie.domain, url)),
        key=lambda cookie: (cookie.name, cookie.domain),
    )


def path_for(profile_dir: Path, name: str) -> Path:
    """The jar path: one jar per profile, beside the profile, named for JSON.

    solver_probe.py:86 wrote the measured run's zendriver pickle to
    ``<name>.cookies.dat``. This module writes JSON, so it takes a JSON name and
    never claims the path zendriver's own save/load owns.
    """
    return profile_dir / f"{name}.cookies.json"


def save(path: Path, cookies: Iterable[Cookie], url: str) -> int:
    """Write the filtered jar and return how many cookies made it in.

    Filtering on write is what makes a jar something a reader can reason about;
    filtering only on read would leave a jar on disk that looks like it holds
    more than the module would ever load.
    """
    kept = filter_cookies(cookies, url)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = json.dumps({"url": url, "cookies": [asdict(cookie) for cookie in kept]}, indent=1) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(kept)


def load(path: Path, url: str) -> list[Cookie]:
    """Read a jar back, re-applying the filter rather than trusting the file.

    A jar is data on disk and anything can widen one by hand; the scope is
    decided here, and a jar written for one site is not replayed onto another.
    Returns ``[]`` for a jar that is not there, because a missing jar is the
    cold-start case and not an error.
    """
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    raw = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise ValueError(f"invalid cookie jar {path}: expected a cookies array")
    cookies = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"invalid cookie jar {path}: cookie {index} must be an object")
        if any(not isinstance(item.get(key), str) for key in ("name", "domain", "value")):
            raise ValueError(f"invalid cookie jar {path}: cookie {index} requires string name, domain and value")
        if any(not isinstance(item.get(key, False), bool) for key in ("secure", "http_only")):
            raise ValueError(f"invalid cookie jar {path}: cookie {index} requires boolean flags")
        expires = item.get("expires")
        if expires is not None and (type(expires) not in (int, float) or not math.isfinite(expires)):
            raise ValueError(f"invalid cookie jar {path}: cookie {index} requires a finite expiry or null")
        if not isinstance(item.get("path", "/"), str) or item.get("same_site") not in (None, "Strict", "Lax", "None"):
            raise ValueError(f"invalid cookie jar {path}: cookie {index} has invalid path or same_site")
        cookies.append(Cookie(
            name=item["name"], domain=item["domain"], value=item["value"],
            expires=expires, secure=item.get("secure", False), same_site=item.get("same_site"),
            path=item.get("path", "/"), http_only=item.get("http_only", False),
        ))
    return filter_cookies(cookies, url)


def clear_locks(profile_dir: Path) -> int:
    """Remove Chromium locks only after proving their local owner has exited."""
    present = []
    for name in PROFILE_LOCKS:
        path = profile_dir / name
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        present.append(path)
    if not present:
        return 0
    lock = profile_dir / "SingletonLock"
    try:
        host, pid_text = str(lock.readlink()).rsplit("-", 1)
        pid = int(pid_text)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"profile lock owner is unknown: {lock}") from error
    if host != socket.gethostname() or pid <= 0:
        raise RuntimeError(f"profile lock is not a verifiable local owner: {lock}")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        raise RuntimeError(f"profile lock owner cannot be checked: {lock}") from error
    else:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError) as error:
            raise RuntimeError(f"profile lock owner cannot be checked: {lock}") from error
        if state != "Z":
            raise RuntimeError(f"profile lock owner is still running: {lock}")
    removed = 0
    for path in sorted(present, key=lambda path: path == lock):
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            continue
    return removed
