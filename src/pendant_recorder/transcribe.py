"""Local speech-to-text: mlx-whisper wrapper, a test fake, and the pending-clip runner."""
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Protocol

import mlx_whisper

from pendant_recorder.audio import to_wav16k
from pendant_recorder.db import Database
from pendant_recorder.models import ClipRecord, Segment, Transcript, Word
from pendant_recorder.paths import Paths

log = logging.getLogger(__name__)


class Transcriber(Protocol):
    def transcribe(self, wav: Path) -> Transcript: ...


class MlxWhisperTranscriber:
    def __init__(self, model: str, language: str):
        self.model = model
        self.language = language
        os.environ["HF_HUB_OFFLINE"] = "1"

    def transcribe(self, wav: Path) -> Transcript:
        r = mlx_whisper.transcribe(
            str(wav), path_or_hf_repo=self.model, language=self.language, word_timestamps=True
        )
        segments = [
            Segment(
                start_s=s["start"], end_s=s["end"], text=s["text"],
                avg_logprob=s["avg_logprob"], no_speech_prob=s["no_speech_prob"],
                words=[
                    Word(start_s=w["start"], end_s=w["end"], word=w["word"], probability=w["probability"])
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
    def __init__(self, by_name: dict[str, "Transcript | Exception"], default: Optional[Transcript] = None):
        self.by_name = by_name
        self.default = default

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
                db.set_transcript(clip.clip_id, t, classify(clip, t), int(time.time() * 1000))
                done += 1
            except Exception:
                log.exception("transcription failed for %s", clip.clip_id)
                db.set_classification(clip.clip_id, "failed")
                failed += 1
    return done, failed
