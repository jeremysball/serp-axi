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
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

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
    """

    name: str
    domain: str
    value: str
    expires: float | None = None
    secure: bool = False
    same_site: str | None = None


def base_domain(host: str) -> str:
    """The registrable-ish base of a host: the last two labels.

    solver_probe.py:30 `".".join(host.split(".")[-2:])`, with the scheme and
    path stripped the way solver_probe.py:29 does for its own URLs.
    """
    host = re.sub(r"^www\.", "", host.split("/")[0]).lower()
    return ".".join(host.split(".")[-2:])


def keeps(name: str, domain: str, url: str) -> bool:
    """Whether one cookie may travel with a fetch for ``url``.

    solver_probe.py:31, with one correction and the reason recorded: the spike
    filtered on ``domain.lstrip(".").endswith(base)``, and ``"evil-example.com"
    .endswith("example.com")`` is true, so a cookie scoped to a lookalike domain
    passed the filter. The match has to stop at a label boundary.
    """
    if name not in KEEP:
        return False
    host = re.sub(r"^www\.", "", url.split("/")[2]).lower()
    base = base_domain(host)
    scope = domain.lstrip(".").lower()
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
    """The measured jar name: one jar per profile, beside the profile.

    solver_probe.py:86 `os.path.join(PROFILES, name + ".cookies.dat")`.
    """
    return profile_dir / f"{name}.cookies.dat"


def save(path: Path, cookies: Iterable[Cookie], url: str) -> int:
    """Write the filtered jar and return how many cookies made it in.

    Filtering on write is what makes a jar something a reader can reason about;
    filtering only on read would leave a jar on disk that looks like it holds
    more than the module would ever load.
    """
    kept = filter_cookies(cookies, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"url": url, "cookies": [asdict(cookie) for cookie in kept]}, indent=1) + "\n")
    return len(kept)


def load(path: Path, url: str) -> list[Cookie]:
    """Read a jar back, re-applying the filter rather than trusting the file.

    A jar is data on disk and anything can widen one by hand; the scope is
    decided here, and a jar written for one site is not replayed onto another.
    Returns ``[]`` for a jar that is not there, because a missing jar is the
    cold-start case and not an error.
    """
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text())
    except (ValueError, OSError):
        return []
    raw = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    cookies = [
        Cookie(
            name=str(item.get("name", "")),
            domain=str(item.get("domain", "")),
            value=str(item.get("value", "")),
            expires=item.get("expires"),
            secure=bool(item.get("secure", False)),
            same_site=item.get("same_site"),
        )
        for item in raw
        if isinstance(item, dict)
    ]
    return filter_cookies(cookies, url)


def clear_locks(profile_dir: Path) -> int:
    """Remove the locks a SIGKILLed browser left behind.

    solver_probe.py:35-41. Without this the next launch stalls on a lock whose
    owner is already gone, which reads as a hang rather than a stale file.
    """
    removed = 0
    for name in PROFILE_LOCKS:
        try:
            (profile_dir / name).unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return removed
