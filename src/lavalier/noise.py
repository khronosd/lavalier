"""Speech-versus-noise classification from loudness and transcript confidence."""
from lavalier.config import Config
from lavalier.models import ClipRecord, Transcript


def classify(clip: ClipRecord, t: Transcript, cfg: Config) -> str:
    """Return "noise" or "speech". Pure: reads only clip.mean_db, t.segments and cfg."""
    if clip.mean_db is not None and clip.mean_db < cfg.noise_mean_db:
        return "noise"
    if not any(s.avg_logprob is not None and s.avg_logprob > cfg.noise_logprob for s in t.segments):
        return "noise"
    confident = sum(1 for s in t.segments for w in s.words
                    if w.probability is not None and w.probability >= cfg.noise_word_p)
    if confident < cfg.noise_min_words:
        return "noise"
    return "speech"
