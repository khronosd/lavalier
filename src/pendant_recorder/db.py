"""SQLite state store: dedup pages, captures, clips, transcripts, events, conversations."""

import json
from contextlib import contextmanager, nullcontext
import sqlite3
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from pendant_recorder.models import (
    ClipRecord,
    Conversation,
    EventRecord,
    PageKey,
    Segment,
    Transcript,
    Word,
)


def now_ms() -> int:
    return int(time.time() * 1000)


class SchemaTooNewError(RuntimeError):
    """The state database was written by a newer pendant-recorder."""


def _run_script(c: sqlite3.Connection, script: str) -> None:
    """Run DDL statements one by one: executescript would commit and escape the transaction."""
    for stmt in script.split(";"):
        if stmt.strip():
            c.execute(stmt)


def _migrate_1(c: sqlite3.Connection) -> None:
    _run_script(
        c,
        """
        CREATE TABLE captures (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            message_count INTEGER NOT NULL,
            complete INTEGER NOT NULL,
            decoded INTEGER NOT NULL DEFAULT 0,
            imported_at_ms INTEGER NOT NULL
        );
        CREATE TABLE pages (
            run INTEGER NOT NULL,
            "index" INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            capture_id INTEGER NOT NULL REFERENCES captures(id),
            session INTEGER NOT NULL,
            ingest_type INTEGER NOT NULL,
            absolute_ms INTEGER NOT NULL,
            UNIQUE (run, "index", sha256)
        );
        CREATE TABLE clips (
            clip_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            day TEXT NOT NULL,
            first_ms INTEGER NOT NULL,
            last_ms INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            first_page INTEGER NOT NULL,
            last_page INTEGER NOT NULL,
            run INTEGER NOT NULL,
            capture_id INTEGER NOT NULL,
            opened_with_start_marker INTEGER NOT NULL,
            closed_with_stop_marker INTEGER NOT NULL,
            clock_suspect INTEGER NOT NULL,
            mean_db REAL,
            peak_db REAL,
            classification TEXT,
            transcribed_at INTEGER,
            transcript_text TEXT,
            language TEXT,
            model TEXT
        );
        CREATE INDEX clips_day ON clips(day);
        CREATE TABLE segments (
            clip_id TEXT NOT NULL REFERENCES clips(clip_id),
            seq INTEGER NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            text TEXT NOT NULL,
            avg_logprob REAL NOT NULL,
            no_speech_prob REAL NOT NULL,
            PRIMARY KEY (clip_id, seq)
        );
        CREATE TABLE words (
            clip_id TEXT NOT NULL,
            segment_seq INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            word TEXT NOT NULL,
            probability REAL NOT NULL,
            PRIMARY KEY (clip_id, segment_seq, seq)
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            page_index INTEGER NOT NULL,
            absolute_ms INTEGER NOT NULL,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            capture_id INTEGER NOT NULL
        );
        CREATE INDEX events_ms ON events(absolute_ms);
        CREATE TABLE conversations (
            conversation_id TEXT PRIMARY KEY,
            day TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            speech_ms INTEGER NOT NULL,
            star_ms TEXT NOT NULL,
            label TEXT
        );
        CREATE INDEX conversations_day ON conversations(day);
        CREATE TABLE conversation_clips (
            conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
            position INTEGER NOT NULL,
            clip_id TEXT NOT NULL,
            PRIMARY KEY (conversation_id, position)
        );
        CREATE TABLE pins (conversation_id TEXT PRIMARY KEY);
        CREATE TABLE day_state (day TEXT PRIMARY KEY, dirty INTEGER NOT NULL);
        """
    )


# Numbered, applied in order (the status table is bootstrapped by migrate()); the status row "schema_version" records the last applied.
MIGRATIONS = [_migrate_1]

_CLIP_COLS = (
    "clip_id, path, day, first_ms, last_ms, chunk_count, first_page, last_page, run, "
    "capture_id, opened_with_start_marker, closed_with_stop_marker, clock_suspect, "
    "mean_db, peak_db, classification, transcribed_at"
)


def _clip_from_row(r: sqlite3.Row) -> ClipRecord:
    return ClipRecord(
        clip_id=r["clip_id"],
        path=r["path"],
        day=date.fromisoformat(r["day"]),
        first_ms=r["first_ms"],
        last_ms=r["last_ms"],
        chunk_count=r["chunk_count"],
        first_page=r["first_page"],
        last_page=r["last_page"],
        run=r["run"],
        capture_id=r["capture_id"],
        opened_with_start_marker=bool(r["opened_with_start_marker"]),
        closed_with_stop_marker=bool(r["closed_with_stop_marker"]),
        clock_suspect=bool(r["clock_suspect"]),
        mean_db=r["mean_db"],
        peak_db=r["peak_db"],
        classification=r["classification"],
        transcribed_at=r["transcribed_at"],
    )


def _local_day_bounds_ms(day: date) -> tuple[int, int]:
    start = datetime.combine(day, dtime.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), dtime.min).astimezone()
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


class Database:
    def __init__(self, path: Path):
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._depth = 0

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run several writes as one unit: commit on success, roll back on error.

        Every write method defers its own commit while inside it. A nested call joins the
        outer transaction; only the outermost one commits or rolls back. The explicit BEGIN
        also covers DDL, which sqlite3 would otherwise run outside any transaction.
        """
        if self._depth:
            self._depth += 1
            try:
                yield self._conn
            finally:
                self._depth -= 1
            return
        self._conn.execute("BEGIN")
        self._depth = 1
        try:
            yield self._conn
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            self._depth = 0

    def _write_scope(self):
        return nullcontext() if self._depth else self._conn

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def migrate(self) -> None:
        with self.transaction():
            self._conn.execute("CREATE TABLE IF NOT EXISTS status (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        current = int(self.get_status("schema_version") or 0)
        if current > len(MIGRATIONS):
            raise SchemaTooNewError(
                f"state database schema version {current} is newer than this pendant-recorder "
                f"supports ({len(MIGRATIONS)}); upgrade pendant-recorder before using this state root"
            )
        for n, fn in enumerate(MIGRATIONS, start=1):
            if n <= current:
                continue
            with self.transaction():  # the migration and its version bump land together or not at all
                fn(self._conn)
                self.set_status("schema_version", str(n))

    # captures

    def add_capture(self, path: str, sha256: str, message_count: int, complete: bool) -> int:
        """path is relative to the state root, like clip paths."""
        with self._write_scope():
            cur = self._conn.execute(
                "INSERT INTO captures (path, sha256, message_count, complete, imported_at_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, sha256, message_count, int(complete), now_ms()),
            )
        return cur.lastrowid

    def capture_by_sha(self, sha256: str) -> Optional[int]:
        r = self._conn.execute("SELECT id FROM captures WHERE sha256 = ?", (sha256,)).fetchone()
        return r["id"] if r else None

    def mark_capture_decoded(self, capture_id: int) -> None:
        with self._write_scope():
            self._conn.execute("UPDATE captures SET decoded = 1 WHERE id = ?", (capture_id,))

    def capture_decoded(self, capture_id: int) -> bool:
        r = self._conn.execute("SELECT decoded FROM captures WHERE id = ?", (capture_id,)).fetchone()
        return bool(r and r["decoded"])

    def captures_decoded_before(self, cutoff_ms: int) -> list[tuple[int, str]]:
        rows = self._conn.execute(
            "SELECT id, path FROM captures WHERE decoded = 1 AND imported_at_ms <= ? ORDER BY id",
            (cutoff_ms,),
        ).fetchall()
        return [(r["id"], r["path"]) for r in rows]

    def clips_with_audio_for_capture(self, capture_id: int) -> int:
        r = self._conn.execute(
            "SELECT COUNT(*) AS n FROM clips WHERE capture_id = ? AND path != ''", (capture_id,)
        ).fetchone()
        return r["n"]

    # pages

    def page_seen(self, key: PageKey) -> bool:
        r = self._conn.execute(
            'SELECT 1 FROM pages WHERE run = ? AND "index" = ? AND sha256 = ?',
            (key.run, key.index, key.sha256),
        ).fetchone()
        return r is not None

    def pages_for_capture(self, capture_id: int) -> list[PageKey]:
        """The pages this capture registered first, in stream (insertion) order."""
        rows = self._conn.execute(
            'SELECT run, "index", sha256 FROM pages WHERE capture_id = ? ORDER BY rowid', (capture_id,)
        ).fetchall()
        return [PageKey(r["run"], r["index"], r["sha256"]) for r in rows]

    def add_page(self, key: PageKey, capture_id: int, session: int, ingest_type: int, absolute_ms: int) -> None:
        with self._write_scope():
            self._conn.execute(
                'INSERT INTO pages (run, "index", sha256, capture_id, session, ingest_type, absolute_ms) '
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key.run, key.index, key.sha256, capture_id, session, ingest_type, absolute_ms),
            )

    # clips

    def add_clip(self, c: ClipRecord) -> None:
        with self._write_scope():
            self._conn.execute(
                f"INSERT INTO clips ({_CLIP_COLS}) VALUES ({', '.join('?' * 17)})",
                (
                    c.clip_id, c.path, c.day.isoformat(), c.first_ms, c.last_ms, c.chunk_count,
                    c.first_page, c.last_page, c.run, c.capture_id,
                    int(c.opened_with_start_marker), int(c.closed_with_stop_marker), int(c.clock_suspect),
                    c.mean_db, c.peak_db, c.classification, c.transcribed_at,
                ),
            )

    def _clips(self, where: str, params: tuple = ()) -> list[ClipRecord]:
        rows = self._conn.execute(
            f"SELECT {_CLIP_COLS} FROM clips WHERE {where} ORDER BY first_ms, clip_id", params
        ).fetchall()
        return [_clip_from_row(r) for r in rows]

    def clip(self, clip_id: str) -> Optional[ClipRecord]:
        found = self._clips("clip_id = ?", (clip_id,))
        return found[0] if found else None

    def clips_for_day(self, day: date) -> list[ClipRecord]:
        return self._clips("day = ?", (day.isoformat(),))

    def clips_needing_loudness(self) -> list[ClipRecord]:
        return self._clips("path != '' AND mean_db IS NULL AND (classification IS NULL OR classification != 'failed')")

    def clips_needing_transcript(self) -> list[ClipRecord]:
        return self._clips("path != '' AND transcribed_at IS NULL AND classification IS NULL")

    def set_loudness(self, clip_id: str, mean_db: float, peak_db: float) -> None:
        with self._write_scope():
            self._conn.execute(
                "UPDATE clips SET mean_db = ?, peak_db = ? WHERE clip_id = ?", (mean_db, peak_db, clip_id)
            )

    def set_transcript(self, clip_id: str, t: Transcript, classification: str, transcribed_at_ms: int) -> None:
        with self._write_scope():
            self._conn.execute("DELETE FROM words WHERE clip_id = ?", (clip_id,))
            self._conn.execute("DELETE FROM segments WHERE clip_id = ?", (clip_id,))
            for i, s in enumerate(t.segments):
                self._conn.execute(
                    "INSERT INTO segments (clip_id, seq, start_s, end_s, text, avg_logprob, no_speech_prob) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (clip_id, i, s.start_s, s.end_s, s.text, s.avg_logprob, s.no_speech_prob),
                )
                for j, w in enumerate(s.words):
                    self._conn.execute(
                        "INSERT INTO words (clip_id, segment_seq, seq, start_s, end_s, word, probability) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (clip_id, i, j, w.start_s, w.end_s, w.word, w.probability),
                    )
            self._conn.execute(
                "UPDATE clips SET transcript_text = ?, language = ?, model = ?, classification = ?, "
                "transcribed_at = ? WHERE clip_id = ?",
                (t.text, t.language, t.model, classification, transcribed_at_ms, clip_id),
            )

    def transcript(self, clip_id: str) -> Optional[Transcript]:
        r = self._conn.execute(
            "SELECT transcript_text, language, model FROM clips WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        if r is None or r["transcript_text"] is None:
            return None
        words: dict[int, list[Word]] = {}
        for w in self._conn.execute(
            "SELECT * FROM words WHERE clip_id = ? ORDER BY segment_seq, seq", (clip_id,)
        ):
            words.setdefault(w["segment_seq"], []).append(
                Word(w["start_s"], w["end_s"], w["word"], w["probability"])
            )
        segments = [
            Segment(s["start_s"], s["end_s"], s["text"], s["avg_logprob"], s["no_speech_prob"], words.get(s["seq"], []))
            for s in self._conn.execute("SELECT * FROM segments WHERE clip_id = ? ORDER BY seq", (clip_id,))
        ]
        return Transcript(r["transcript_text"], r["language"], r["model"], segments)

    def set_classification(self, clip_id: str, classification: str) -> None:
        with self._write_scope():
            self._conn.execute("UPDATE clips SET classification = ? WHERE clip_id = ?", (classification, clip_id))

    def reset_failed_clips(self) -> int:
        """Return failed clips to the loudness and transcription queues."""
        with self._write_scope():
            cur = self._conn.execute(
                "UPDATE clips SET classification = NULL, transcribed_at = NULL, mean_db = NULL, peak_db = NULL "
                "WHERE classification = 'failed'"
            )
        return cur.rowcount

    def count_failed_clips(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM clips WHERE classification = 'failed'").fetchone()["n"]

    def clips_with_audio_older_than(self, cutoff_ms: int) -> list[ClipRecord]:
        return self._clips("path != '' AND transcribed_at IS NOT NULL AND transcribed_at <= ?", (cutoff_ms,))

    def clear_clip_path(self, clip_id: str) -> None:
        with self._write_scope():
            self._conn.execute("UPDATE clips SET path = '' WHERE clip_id = ?", (clip_id,))

    # events

    def add_event(self, e: EventRecord) -> None:
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO events (page_index, absolute_ms, type, payload, capture_id) VALUES (?, ?, ?, ?, ?)",
                (e.page_index, e.absolute_ms, e.type, json.dumps(e.payload), e.capture_id),
            )

    def events_for_day(self, day: date, types: Optional[list[str]] = None) -> list[EventRecord]:
        lo, hi = _local_day_bounds_ms(day)
        sql = "SELECT * FROM events WHERE absolute_ms >= ? AND absolute_ms < ?"
        params: list = [lo, hi]
        if types is not None:
            sql += f" AND type IN ({', '.join('?' * len(types))})"
            params += types
        rows = self._conn.execute(sql + " ORDER BY absolute_ms, id", params).fetchall()
        return [
            EventRecord(r["page_index"], r["absolute_ms"], r["type"], json.loads(r["payload"]), r["capture_id"])
            for r in rows
        ]

    # conversations

    def replace_conversations(self, day: date, convs: list[Conversation]) -> None:
        iso = day.isoformat()
        with self._write_scope():
            self._conn.execute(
                "DELETE FROM conversation_clips WHERE conversation_id IN "
                "(SELECT conversation_id FROM conversations WHERE day = ?)",
                (iso,),
            )
            self._conn.execute("DELETE FROM conversations WHERE day = ?", (iso,))
            for c in convs:
                self._conn.execute(
                    "INSERT INTO conversations (conversation_id, day, start_ms, end_ms, speech_ms, star_ms, label) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (c.conversation_id, iso, c.start_ms, c.end_ms, c.speech_ms, json.dumps(c.star_ms), c.label),
                )
                self._conn.executemany(
                    "INSERT INTO conversation_clips (conversation_id, position, clip_id) VALUES (?, ?, ?)",
                    [(c.conversation_id, i, cid) for i, cid in enumerate(c.clip_ids)],
                )

    def conversations_for_day(self, day: date) -> list[Conversation]:
        rows = self._conn.execute(
            "SELECT c.*, p.conversation_id IS NOT NULL AS pinned FROM conversations c "
            "LEFT JOIN pins p ON p.conversation_id = c.conversation_id WHERE c.day = ? ORDER BY c.start_ms",
            (day.isoformat(),),
        ).fetchall()
        out = []
        for r in rows:
            clip_ids = [
                x["clip_id"]
                for x in self._conn.execute(
                    "SELECT clip_id FROM conversation_clips WHERE conversation_id = ? ORDER BY position",
                    (r["conversation_id"],),
                )
            ]
            out.append(
                Conversation(
                    r["conversation_id"], day, r["start_ms"], r["end_ms"], r["speech_ms"],
                    clip_ids, json.loads(r["star_ms"]), bool(r["pinned"]), r["label"],
                )
            )
        return out

    def pin(self, conversation_id: str) -> None:
        with self._write_scope():
            self._conn.execute("INSERT OR IGNORE INTO pins (conversation_id) VALUES (?)", (conversation_id,))

    def unpin(self, conversation_id: str) -> None:
        with self._write_scope():
            self._conn.execute("DELETE FROM pins WHERE conversation_id = ?", (conversation_id,))

    def days_with_clips(self) -> list[date]:
        rows = self._conn.execute("SELECT DISTINCT day FROM clips ORDER BY day").fetchall()
        return [date.fromisoformat(r["day"]) for r in rows]

    def days_dirty(self) -> list[date]:
        rows = self._conn.execute("SELECT day FROM day_state WHERE dirty = 1 ORDER BY day").fetchall()
        return [date.fromisoformat(r["day"]) for r in rows]

    def mark_day_dirty(self, day: date) -> None:
        self._set_dirty(day, 1)

    def mark_day_clean(self, day: date) -> None:
        self._set_dirty(day, 0)

    def _set_dirty(self, day: date, dirty: int) -> None:
        with self._write_scope():
            self._conn.execute(
                "INSERT INTO day_state (day, dirty) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET dirty = excluded.dirty",
                (day.isoformat(), dirty),
            )

    # status

    def set_status(self, key: str, value: str) -> None:
        with self._write_scope():
            self._conn.execute("INSERT OR REPLACE INTO status (key, value) VALUES (?, ?)", (key, value))

    def get_status(self, key: str) -> Optional[str]:
        r = self._conn.execute("SELECT value FROM status WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None
