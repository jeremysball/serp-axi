"""Audio helper tests, not evidence of live browser/audio integration."""

from __future__ import annotations

import importlib

import pytest

from ladder_cli.rungs import whisper


@pytest.fixture(autouse=True)
def fresh_model(monkeypatch):
    """Start each test with an unloaded model.

    The memo is process-wide by design (it is the fix this module makes), so a
    test that follows one which loaded would otherwise see the cache and never
    reach its own construction site. Resetting the module state rather than
    adding a production reset keeps the test-only surface out of the rung.
    """
    monkeypatch.setattr(whisper, "_model", None)


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


def test_importing_the_module_loads_nothing(monkeypatch) -> None:
    """04-tdd 1.7: laziness is asserted as zero model loads before first need.

    The 80-in-100 case pays rung 1's cost alone. A model built at import would
    spend Whisper's construction on a scrape that never met a challenge.
    Re-executing the module is what makes this a claim about import rather than
    about the cache a previous test happened to leave behind.
    """
    factory = RecordingFactory()
    monkeypatch.setattr(whisper, "_build", factory)
    assert whisper.load() is factory.model
    assert len(factory.calls) == 1
    module = importlib.reload(whisper)
    assert module._model is None


def test_the_helper_reuses_one_model_within_its_process(monkeypatch) -> None:
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


def test_the_round_budget_does_not_drain_a_lazy_clip_producer(monkeypatch) -> None:
    """`list(clips)[:3]` materialised the whole producer before slicing it.

    A challenge offering more clips than the three the run answers would pay to
    discover every one of them. `islice` reads exactly the budget.
    """
    monkeypatch.setattr(whisper, "transcribe", lambda path: f"Clip {path}")
    pulled: list[int] = []

    def clips():
        for index in range(10):
            pulled.append(index)
            yield f"cl{index}"

    answers = whisper.answer_rounds(clips())

    assert answers == ["clip cl0", "clip cl1", "clip cl2"]
    assert pulled == [0, 1, 2], f"the producer was pulled {len(pulled)} times for a 3-round budget"


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
