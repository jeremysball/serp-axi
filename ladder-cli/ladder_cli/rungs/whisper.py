"""Rung 5: Whisper on an audio reCAPTCHA, as the rung-4 fallback.

What this module fixes is one line of the measured run: q5_audio.py:44 built
``WhisperModel("base.en", ...)`` inside its per-URL loop and re-paid the model's
construction on every fetch, against medians of 21.1s (04-tdd 1.4). The model is
a resource of the CLI's life, so it is built on first audio need and then kept,
which is the rule the browser rungs already follow for their profiles.

The construction site is one private function. That is deliberate: it is the
seam that lets the suite assert "zero model loads before first audio need"
(04-tdd 1.7) and "one build per CLI life" without importing faster-whisper,
which is the ``audio`` extra and absent from a default install.

What is here is the audio half of the rung. The browser half, clicking the
challenge's audio button and typing the answer back (q5_audio.py:28-48), needs
a live challenge page and has no recorded fixture, so it is not written yet and
nothing pretends otherwise: ``fetch`` climbs with rung 4 and an audio challenge
comes back ``blocked``, exactly as rung 4 left it.
"""

from __future__ import annotations

import re
from typing import Any

from . import RungResult, browser_judge

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
_loads = 0


def _build(**kwargs: Any) -> Any:
    """Construct the model. The one place faster-whisper is imported.

    Deferred like every other browser or model tool here: the resident child
    owes its ready line before it touches one (04-tdd 1.4).
    """
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL_NAME, **kwargs)


def load() -> Any:
    """The model, constructed once per CLI life and then reused.

    Nothing is built at import and nothing is built before an audio clip is
    actually in hand, so the 80-in-100 case that never meets a challenge pays
    nothing at all.
    """
    global _model, _loads
    if _model is None:
        model = _build(device=DEVICE, compute_type=COMPUTE_TYPE)
        _model = model
        _loads += 1
    return _model


def model_loads() -> int:
    """How many times the model has been built in this process.

    The number the laziness and once-per-life assertions read. A CLI that
    loaded once and one that loaded per URL look identical from outside and are
    21.1s apart per fetch, so the count is part of the contract.
    """
    return _loads


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
    """
    return [answer_for(transcribe(clip)) for clip in list(clips)[:MAX_ROUNDS]]


def fetch(url: str) -> dict[str, Any]:
    """Retrieve a page as ``{"title", "text", "status"}``, or raise.

    Rung 5 is rung 4's fallback rather than a different fetcher: it climbs to
    the headed browser and, when what that returns is an audio reCAPTCHA,
    answers the clip instead of reporting the challenge. Until the browser half
    lands, an audio challenge is reported as the challenge it is rather than
    solved, so the ladder is never told a page opened when it did not.
    """
    from . import headed

    return headed.fetch(url)


judge = browser_judge
