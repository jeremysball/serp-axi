"""Rung 5: Whisper on an audio reCAPTCHA, as the rung-4 fallback.

The measured run built ``WhisperModel("base.en", ...)`` inside its per-URL loop
(q5_audio.py:44) and paid the model's construction on every fetch against
medians of 21.1s (04-tdd 1.4). What this module fixes is that: the model is a
resource of the CLI's life, not of one fetch.

Nothing here reaches a network or loads a model at import. The construction
site is one private function, which is the seam these tests read through.
"""

from __future__ import annotations

import importlib

import pytest

from ladder_cli.rungs import RungVerdict, browser_judge, whisper


@pytest.fixture(autouse=True)
def fresh_model(monkeypatch):
    """Start each test with an unloaded model.

    The memo is process-wide by design (it is the fix this module makes), so a
    test that follows one which loaded would otherwise see the cache and never
    reach its own construction site. Resetting the module state rather than
    adding a production reset keeps the test-only surface out of the rung.
    """
    monkeypatch.setattr(whisper, "_model", None)
    monkeypatch.setattr(whisper, "_loads", 0)


class Simple:
    def __init__(self, text: str) -> None:
        self.text = text


class RecordingFactory:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.model = object()

    def __call__(self, **kwargs: object):
        self.calls.append(kwargs)
        return self.model


def test_importing_the_module_loads_nothing() -> None:
    """04-tdd 1.7: laziness is asserted as zero model loads before first need.

    The 80-in-100 case pays rung 1's cost alone. A model built at import would
    spend Whisper's construction on a scrape that never met a challenge.
    Re-executing the module is what makes this a claim about import rather than
    about the cache a previous test happened to leave behind.
    """
    module = importlib.reload(whisper)
    assert module.model_loads() == 0
    assert module._model is None


def test_the_model_is_built_once_per_cli_life_not_once_per_fetch(monkeypatch) -> None:
    factory = RecordingFactory()
    monkeypatch.setattr(whisper, "_build", factory)

    assert whisper.load() is factory.model
    assert whisper.load() is factory.model
    assert whisper.load() is factory.model

    assert len(factory.calls) == 1, "a second fetch re-paid the model's construction"


def test_the_construction_carries_the_measured_arguments(monkeypatch) -> None:
    # q5_audio.py:44 `WhisperModel("base.en", device="cpu", compute_type="int8")`
    factory = RecordingFactory()
    monkeypatch.setattr(whisper, "_build", factory)

    whisper.load()

    assert factory.calls == [{"device": "cpu", "compute_type": "int8"}]
    assert whisper.MODEL_NAME == "base.en"
    assert whisper.DEVICE == "cpu"
    assert whisper.COMPUTE_TYPE == "int8"


def test_transcription_carries_the_measured_arguments(monkeypatch) -> None:
    # q5_audio.py:47 `model.transcribe(f.name, language="en", beam_size=5)`
    calls: list[tuple] = []

    class FakeModel:
        def transcribe(self, path: str, **kwargs: object) -> tuple[list, object]:
            calls.append((path, kwargs))
            return ([Simple(text="Two words")], None)

    monkeypatch.setattr(whisper, "_build", lambda **kwargs: FakeModel())

    assert whisper.transcribe("clip.mp3") == "Two words"
    assert calls == [("clip.mp3", {"language": "en", "beam_size": 5})]
    assert whisper.BEAM_SIZE == 5
    assert whisper.LANGUAGE == "en"


def test_the_answer_is_the_measured_sanitised_form_of_the_transcript() -> None:
    # q5_audio.py:48 `re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()`
    assert whisper.answer_for("Word, TWO Three!") == "word two three"
    assert whisper.answer_for("  spaced  ") == "spaced"
    assert whisper.answer_for("Numbers 123 and symbols #$%") == "numbers 123 and symbols"
    assert whisper.answer_for("") == ""


def test_the_clip_is_asked_for_at_most_the_measured_number_of_rounds() -> None:
    # q5_audio.py:42 `for round_ in range(3)`: reCAPTCHA sometimes asks for more
    assert whisper.MAX_ROUNDS == 3


def test_the_measured_loop_stops_at_three_clips_no_matter_how_many_are_offered(monkeypatch) -> None:
    """q5_audio.py:42's `for round_ in range(3)`, as the ceiling it was.

    reCAPTCHA sometimes asks for more than one clip and the run answered three
    of them. Taking every clip offered would answer a fourth the measured run
    never answered, and taking one would leave a challenge unmet.
    """
    monkeypatch.setattr(whisper, "transcribe", lambda path: f"Clip {path}")

    answers = whisper.answer_rounds([f"cl{n}" for n in range(7)])

    assert len(answers) == 3, "the budget is the run's three rounds"
    assert answers == ["clip cl0", "clip cl1", "clip cl2"]


def test_a_model_that_fails_to_build_does_not_leave_a_broken_rung_hanging(monkeypatch) -> None:
    """A missing optional dependency is a rung that cannot answer, not a crash.

    faster-whisper is the `audio` extra and is absent from a default install, so
    this is the case a plain `uv sync` produces.
    """

    def boom(**kwargs: object):
        raise ModuleNotFoundError("No module named 'faster_whisper")

    monkeypatch.setattr(whisper, "_build", boom)

    with pytest.raises(ModuleNotFoundError):
        whisper.load()
    assert whisper.model_loads() == 0, "a failed construction is not a load"


def test_rung_five_is_registered_under_its_wire_name() -> None:
    from ladder_cli.rungs import MODULES, RUNGS

    assert RUNGS[-1] == "whisper"
    assert MODULES["whisper"] is whisper


def test_the_judge_is_the_browser_rungs_own() -> None:
    """Rung 5 reads the page rung 4 left; it does not invent a new rule set."""
    assert whisper.judge is browser_judge
    result = whisper.judge({"title": "Gone", "text": "nope", "status": 404})
    assert result.verdict is RungVerdict.DEAD



def _request(**overrides) -> object:
    from ladder_cli.protocol import LadderRequest

    payload = {
        "protocol": 1,
        "url": "https://example.com/",
        "tabState": "fresh",
        "cookieState": "cold",
        "cacheState": "cold",
        "fingerprintState": "rotate",
        "rungCeiling": 5,
        "profile": None,
        "jarIn": None,
        "jarOut": None,
    }
    payload.update(overrides)
    return LadderRequest.parse(payload)


def test_rung_five_is_never_sent_to_the_killable_subprocess(monkeypatch) -> None:
    """The mechanism the whole claim rests on.

    A subprocess runner means `python -m ladder_cli --rung whisper <url>`, a new
    interpreter per fetch, so any model it builds dies with it. If whisper ever
    reaches the runner, the once-per-life guarantee is gone and nothing here
    would notice.
    """
    from ladder_cli.cli import dispatch
    from ladder_cli.rungs import RungResult, RungVerdict

    seen: list[str] = []

    def spy(rung: str, url: str) -> RungResult:
        seen.append(rung)
        return RungResult(RungVerdict.BLOCKED, reason="subprocess")

    monkeypatch.setattr(whisper, "fetch", lambda url: {"title": "t", "text": "x" * 900, "status": 200})

    dispatch(_request(), runner=spy)

    assert "whisper" not in seen, "rung 5 went to the subprocess and its model died with it"
    assert seen == ["http", "camoufox", "zendriver_cf", "zendriver_headed_cf"]


def test_the_model_is_built_once_across_fetches_in_the_resident_child(monkeypatch) -> None:
    """Two fetches that both need audio must not pay the construction twice.

    This is the amortization the phase is for. It only holds because both
    fetches run in the same long-lived process, which the test above pins; here
    we pin the consequence.
    """
    from ladder_cli.cli import dispatch
    from ladder_cli.rungs import RungResult, RungVerdict

    class FakeModel:
        def transcribe(self, path, **kwargs):
            return ([Simple(text=f"Heard {path}")], None)

    builds: list[dict] = []
    monkeypatch.setattr(whisper, "_build", lambda **kwargs: builds.append(kwargs) or FakeModel())

    def fetch_needing_audio(url: str) -> dict:
        # A fetch that answers an audio clip transcribes it, which loads the model.
        whisper.answer_rounds(["clip-1.mp3", "clip-2.mp3"])
        return {"title": "t", "text": "x" * 900, "status": 200}

    monkeypatch.setattr(whisper, "fetch", fetch_needing_audio)

    def never(rung: str, url: str):
        # Rungs 1 to 4 are meant to be isolated. Only whisper reaching here is a bug.
        if rung == "whisper":
            raise AssertionError("whisper must not be isolated")
        return RungResult(RungVerdict.BLOCKED, reason="subprocess")

    dispatch(_request(), runner=never)
    dispatch(_request(), runner=never)

    assert len(builds) == 1, f"the model was constructed {len(builds)} times across two fetches"
