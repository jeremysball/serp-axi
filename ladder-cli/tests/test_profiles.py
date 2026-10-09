"""Warm browser profile directories.

A profile is warmed once and reused for the CLI's whole life (04-tdd 1.5), so
the layout has one owner. The names are carried from the measured run, which
kept one user-data directory per headed-ness rather than one per request.
"""

from __future__ import annotations

from pathlib import Path

from ladder_cli.state import profiles


def test_a_headless_and_a_headed_profile_are_different_directories(tmp_path: Path) -> None:
    # ladder.py:82 `user_data_dir=os.path.abspath(f"profiles/zd{'_headed' if headed else ''}")`
    assert profiles.zendriver_dir(tmp_path, headed=False) == tmp_path / "zd"
    assert profiles.zendriver_dir(tmp_path, headed=True) == tmp_path / "zd_headed"


def test_the_two_profiles_never_share_a_directory(tmp_path: Path) -> None:
    """A shared profile would let one rung's cookies leak into another's."""
    assert profiles.zendriver_dir(tmp_path, headed=False) != profiles.zendriver_dir(tmp_path, headed=True)


def test_warming_a_profile_reuses_the_same_directory(tmp_path: Path) -> None:
    first = profiles.warm(profiles.zendriver_dir(tmp_path, headed=False))
    second = profiles.warm(profiles.zendriver_dir(tmp_path, headed=False))
    assert first == second
    assert first.is_dir()


def test_warming_is_idempotent_rather_than_a_wipe(tmp_path: Path) -> None:
    target = profiles.zendriver_dir(tmp_path, headed=True)
    warmed = profiles.warm(target)
    (warmed / "Cookies").write_text("kept")
    profiles.warm(target)
    assert (warmed / "Cookies").read_text() == "kept", "a warmed profile must survive to the next request"


def test_the_profiles_directory_is_created_by_warming(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "profiles"
    warmed = profiles.warm(root / "zd")
    assert warmed.is_dir()
    assert root.is_dir()


def test_the_root_can_be_pointed_elsewhere_without_a_chdir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(profiles.ROOT_ENV, str(tmp_path))
    assert profiles.root() == tmp_path


def test_the_root_defaults_to_the_measured_location(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(profiles.ROOT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    assert profiles.root() == Path("profiles")