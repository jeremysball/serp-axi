"""Regression coverage for the named mutation gate itself."""

from pathlib import Path
import ast
import os
import signal
import socket
import subprocess
import sys

import pytest


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import mutations

    monkeypatch.setattr(mutations, "_BASELINE", {})
    return mutations


@pytest.mark.parametrize("timeout", [None, 0.3])
def test_per_rung_budget_mutant_preserves_other_rungs_timeout(gate, timeout):
    belief = next(b for b in gate.BELIEFS if b.name == "no rung carries its own budget")
    expression = ast.Expression(ast.parse(belief.new.strip()).body[0].value)
    code = compile(expression, "<budget-mutant>", "eval")
    budgets = {
        rung: eval(code, {"rung": rung, "timeout_s": timeout, "DEFAULT_RUNG_TIMEOUT_S": 90.0})
        for rung in ("http", "camoufox", "zendriver_cf", "zendriver_headed_cf")
    }
    assert budgets["http"] == 5.0
    expected = 90.0 if timeout is None else timeout
    assert {rung: budgets[rung] for rung in budgets if rung != "http"} == {
        "camoufox": expected, "zendriver_cf": expected, "zendriver_headed_cf": expected,
    }


def test_collection_error_is_an_invalid_mutation(gate, monkeypatch, tmp_path, capsys):
    target = tmp_path / "test_case.py"
    original = "VALUE = 1\n\ndef test_value():\n    assert VALUE == 1\n"
    target.write_text(original)
    monkeypatch.setattr(gate, "LADDER", tmp_path)
    monkeypatch.setattr(gate, "PYTEST", [sys.executable, "-m", "pytest", "-q"])
    monkeypatch.setattr(gate, "BELIEFS", [gate.Belief(
        name="collection errors are not surviving beliefs", path=target,
        old="VALUE = 1", new="VALUE = (", test="test_case.py::test_value",
        why="A collection error cannot establish whether the assertion detects the mutation.",
    )])
    monkeypatch.setattr(sys, "argv", ["mutations.py"])

    assert gate.main() == 1
    output = capsys.readouterr().out
    assert "INVALID   [collection errors are not surviving beliefs]" in output
    assert "1 stale entr(ies)" in output
    assert target.read_text() == original


def test_cache_cleanup_is_limited_to_project_source_and_tests(gate, monkeypatch, tmp_path):
    caches = [tmp_path / part / "__pycache__" for part in ("ladder_cli", "tests", ".venv")]
    for cache in caches:
        cache.mkdir(parents=True)
        (cache / "module.pyc").write_bytes(b"retained dependency cache")
    removed = []
    rmtree = gate.shutil.rmtree

    def record_removal(path, **kwargs):
        removed.append(path)
        return rmtree(path, **kwargs)

    monkeypatch.setattr(gate.shutil, "rmtree", record_removal)
    gate._forget_imports(tmp_path)

    assert removed == caches[:2]
    assert (caches[2] / "module.pyc").read_bytes() == b"retained dependency cache"


def test_cache_cleanup_failure_aborts_the_gate(gate, monkeypatch, tmp_path):
    cache = tmp_path / "ladder_cli" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "blocked.pyc").write_bytes(b"stale bytecode")
    unlink = gate.os.unlink

    def deny_cache_unlink(path, *args, **kwargs):
        if Path(path).name == "blocked.pyc":
            raise PermissionError(13, "cannot remove stale bytecode", str(path))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(gate.os, "unlink", deny_cache_unlink)
    with pytest.raises(PermissionError, match="cannot remove stale bytecode"):
        gate._forget_imports(tmp_path)


@pytest.mark.parametrize("value,expected", [(1, "pass"), (2, "fail")])
def test_test_process_writes_are_confined_to_scratch(gate, monkeypatch, tmp_path, value, expected):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    cache = checkout / "ladder_cli" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "retained.pyc").write_bytes(b"original cache")
    outside = home / "sentinel"
    outside.write_text("untouched")
    target = checkout / "test_case.py"
    target.write_text(
        "from pathlib import Path\nimport os\n"
        f"VALUE = {value}\n"
        "def test_value():\n"
        "    Path('execution-proof').write_text('ran')\n"
        "    assert Path('execution-proof').read_text() == 'ran'\n"
        f"    external = Path({str(outside)!r})\n"
        "    try:\n        external.write_text('changed')\n"
        "    except OSError:\n        pass\n"
        "    Path(os.environ['HOME'], 'test-output').write_text('home write')\n"
        "    assert VALUE == 1\n"
    )
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(gate, "LADDER", checkout)
    monkeypatch.setattr(gate, "PYTEST", [sys.executable, "-m", "pytest", "-q"])

    outcome, last = gate.run_tests("test_case.py::test_value")

    assert outcome == expected, last
    assert {"pass": "1 passed", "fail": "1 failed"}[expected] in last
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before


def test_killing_a_running_mutant_preserves_checkout_source(gate, tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with socket.socket(socket.AF_UNIX) as listener:
        address = str(tmp_path / "ready.sock")
        listener.bind(address)
        listener.listen(1)
        listener.settimeout(30)
        target = checkout / "test_case.py"
        original = (
            "import signal, socket\nVALUE = 1\n\ndef test_value():\n"
            "    if VALUE == 2:\n"
            "        with socket.socket(socket.AF_UNIX) as peer:\n"
            f"            peer.connect({address!r})\n"
            "            peer.sendall(str(VALUE).encode())\n"
            "            signal.pause()\n"
            "    assert VALUE == 1\n"
        )
        target.write_text(original)
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import mutations
mutations.LADDER = Path(sys.argv[2])
mutations.PYTEST = [sys.executable, '-m', 'pytest', '-q']
mutations.BELIEFS = [mutations.Belief(
    'interruption preserves checkout source',
    mutations.LADDER / 'test_case.py', 'VALUE = 1', 'VALUE = 2',
    'test_case.py::test_value', 'A killed gate must not strand a mutant.')]
sys.argv = ['mutations.py']
sys.exit(mutations.main())
"""
        with subprocess.Popen(
            [sys.executable, "-c", code, str(Path(gate.__file__).parent), str(checkout)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, "TMPDIR": str(scratch)},
        ) as process:
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(5)
                    assert peer.recv(16) == b"2"
                    assert target.read_text() == original
                    process.kill()
                    process.wait(timeout=10)
                    assert process.returncode == -signal.SIGKILL
                    assert target.read_text() == original
                    mutants = list(scratch.glob("serp-axi-mutation-*/ladder-cli/test_case.py"))
                    assert len(mutants) == 1
                    assert mutants[0].read_text() == original.replace("VALUE = 1", "VALUE = 2", 1)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=10)


def test_sandbox_startup_failure_is_not_a_kill(gate, monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "bwrap"
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o755)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "test_case.py").write_text("def test_value():\n    assert True\n")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(gate, "LADDER", checkout)
    monkeypatch.setattr(gate, "PYTEST", [sys.executable, "-m", "pytest", "-q"])

    assert gate.run_tests("test_case.py::test_value")[0] == "error"
