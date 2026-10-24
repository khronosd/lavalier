"""Local speech-to-text: mlx-whisper wrapper, a test fake, and the pending-clip runner."""
import logging
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Protocol

# huggingface_hub reads this at import time, so set it before mlx_whisper pulls it in.
# Assign, not setdefault: an exported HF_HUB_OFFLINE=0 must not turn the network back on.
os.environ["HF_HUB_OFFLINE"] = "1"

import huggingface_hub.constants as hf_constants  # noqa: E402
import mlx_whisper  # noqa: E402

from lavalier.audio import to_wav16k
from lavalier.db import Database
from lavalier.models import ClipRecord, Segment, Transcript, Word
from lavalier.paths import Paths

log = logging.getLogger(__name__)


def model_cache_dir(model: str) -> Path:
    """Where huggingface_hub keeps the model (honours HF_HOME / HF_HUB_CACHE)."""
    return Path(hf_constants.HF_HUB_CACHE) / ("models--" + model.replace("/", "--"))


class Transcriber(Protocol):
    def transcribe(self, wav: Path) -> Transcript: ...

    def unavailable_reason(self) -> Optional[str]:
        """Why the stage cannot run in this environment, or None if it can."""
        ...


def _known(x: Optional[float]) -> Optional[float]:
    """mlx_whisper reports NaN when a decoding window's log-probabilities collapsed; sqlite would
    store NaN as NULL anyway, so pass it on as None and let readers treat it as unknown."""
    return None if x is None or math.isnan(x) else float(x)


class MlxWhisperTranscriber:
    def __init__(self, model: str, language: str):
        self.model = model
        self.language = language
        os.environ["HF_HUB_OFFLINE"] = "1"

    def unavailable_reason(self) -> Optional[str]:
        if not model_cache_dir(self.model).exists():
            return f"model {self.model} is not cached; run `lavalier doctor --download-model`"
        return None

    def transcribe(self, wav: Path) -> Transcript:
        r = mlx_whisper.transcribe(
            str(wav), path_or_hf_repo=self.model, language=self.language, word_timestamps=True
        )
        segments = [
            Segment(
                start_s=s["start"], end_s=s["end"], text=s["text"],
                avg_logprob=_known(s["avg_logprob"]), no_speech_prob=_known(s["no_speech_prob"]),
                words=[
                    Word(start_s=w["start"], end_s=w["end"], word=w["word"], probability=_known(w["probability"]))
                    for w in s.get("words", [])
                ],
            )
            for s in r.get("segments", [])
        ]
        return Transcript(
            text=r["text"].strip(), language=r.get("language") or self.language,
            model=self.model, segments=segments,
        )


class FakeTranscriber:
    def __init__(self, by_name: dict[str, "Transcript | Exception"], default: Optional[Transcript] = None,
                 unavailable: Optional[str] = None):
        self.by_name = by_name
        self.default = default
        self.unavailable = unavailable

    def unavailable_reason(self) -> Optional[str]:
        return self.unavailable

    def transcribe(self, wav: Path) -> Transcript:
        if wav.stem in self.by_name:
            v = self.by_name[wav.stem]
            if isinstance(v, Exception):
                raise v
            return v
        if self.default is not None:
            return self.default
        raise KeyError(wav.stem)


def transcribe_pending(
    db: Database, paths: Paths, transcriber: Transcriber,
    classify: Callable[[ClipRecord, Transcript], str],
) -> tuple[int, int]:
    done = failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for clip in db.clips_needing_transcript():
            try:
                wav = Path(tmp) / f"{clip.clip_id}.wav"
                to_wav16k(paths.root / clip.path, wav)
                t = transcriber.transcribe(wav)
                with db.transaction():
                    db.set_transcript(clip.clip_id, t, classify(clip, t), int(time.time() * 1000))
                    db.mark_day_dirty(clip.day)
                done += 1
            except FileNotFoundError:
                # a missing ffmpeg binary or model file: the environment, not this clip
                log.error("transcription stage aborted at %s; clips stay pending", clip.clip_id)
                raise
            except Exception:
                log.exception("transcription failed for %s", clip.clip_id)
                with db.transaction():
                    db.set_classification(clip.clip_id, "failed")
                    db.mark_day_dirty(clip.day)
                failed += 1
    return done, failed
