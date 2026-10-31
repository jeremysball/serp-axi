"""Unwired audio helpers for a future rung 5.

The spike built one model per subprocess and reused it across audio rounds.
These helpers cache it within one process too. Live escalation stops at rung 4:
browser/audio integration and cross-request model reuse remain unfinished.
"""

from __future__ import annotations

import re
from itertools import islice
from typing import Any

# q5_audio.py:44 `WhisperModel("base.en", device="cpu", compute_type="int8")`.
# The small English model on CPU in int8: the clip is short spoken digits and
# words, and the run's 21.1s medians are the thing being cut, not the model
# being tuned.
MODEL_NAME = "base.en"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"
# q5_audio.py:47 `model.transcribe(f.name, language="en", beam_size=5)`
LANGUAGE = "en"
BEAM_SIZE = 5
# q5_audio.py:42 `for round_ in range(3)`: "reCAPTCHA sometimes asks for more
# than one clip", and three is the measured ceiling on that.
MAX_ROUNDS = 3

_model: Any | None = None


def _build(**kwargs: Any) -> Any:
    """Construct the model. The one place faster-whisper is imported.

    Deferred like every other browser or model tool here: the resident child
    owes its ready line before it touches one (04-tdd 1.4).
    """
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL_NAME, **kwargs)


def load() -> Any:
    """The model, lazily constructed and reused within this process."""
    global _model
    if _model is None:
        _model = _build(device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def transcribe(path: str) -> str:
    """One audio clip as text, with the measured decode settings."""
    segments, _info = load().transcribe(path, language=LANGUAGE, beam_size=BEAM_SIZE)
    return " ".join(segment.text for segment in segments).strip()


def answer_for(transcript: str) -> str:
    """The answer to type back, in the form the run typed it.

    q5_audio.py:48 ``re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()``. Whisper
    punctuates what it hears, and the challenge's field wants only the words and
    digits it asked for.
    """
    return re.sub(r"[^a-z0-9 ]", "", transcript.lower()).strip()


def answer_rounds(clips: Any) -> list[str]:
    """The answers for up to ``MAX_ROUNDS`` clips, in the order they were given.

    The measured loop's shape (q5_audio.py:42-48): one clip per round, each
    transcribed and typed back, stopping at three because the challenge
    sometimes asks for more than one and three is where the run stopped.

    ``islice`` reads exactly the budget and no more. Materializing the iterable
    first (``list(clips)[:MAX_ROUNDS]``) drained a lazy producer past the
    three-round budget, so a challenge that offered more clips paid to discover
    them even though the run never answered one.
    """
    return [answer_for(transcribe(clip)) for clip in islice(clips, MAX_ROUNDS)]
