"""SQLite state store: dedup pages, captures, clips, transcripts, events, conversations."""

import json
from dataclasses import dataclass
from contextlib import contextmanager, nullcontext
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional

from lavalier.insights.schema import FollowUp, Insight
from lavalier.models import (
    MIN_VALID_MS,
    ClipRecord,
    Conversation,
    DeviceSnapshot,
    EventRecord,
    PageKey,
    Segment,
    SyncRun,
    Transcript,
    Word,
)


def _u64_to_db(v: int) -> int:
    """SQLite integers are signed 64-bit; storage_instance is an unsigned 64-bit device value."""
    return v - (1 << 64) if v >= (1 << 63) else v


def _u64_from_db(v: int) -> int:
    return v + (1 << 64) if v < 0 else v


def now_ms() -> int:
    return int(time.time() * 1000)


class SchemaTooNewError(RuntimeError):
    """The state database was written by a newer lavalier."""


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


def _local_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).date().isoformat()


def _migrate_2(c: sqlite3.Connection) -> None:
    """Events store the day they are filed under (the capture's day when the clock was unset)."""
    c.execute("ALTER TABLE events ADD COLUMN day TEXT")
    rows = c.execute(
        "SELECT e.id, e.absolute_ms, k.imported_at_ms FROM events e LEFT JOIN captures k ON k.id = e.capture_id"
    ).fetchall()
    for event_id, ms, imported_at_ms in rows:
        # the decode-time capture day is not stored; the import date is the closest stand-in
        when = imported_at_ms if ms < MIN_VALID_MS and imported_at_ms is not None else ms
        c.execute("UPDATE events SET day = ? WHERE id = ?", (_local_date(when), event_id))
    c.execute("CREATE INDEX events_day ON events(day)")


# Numbered, applied in order (the status table is bootstrapped by migrate()); the status row "schema_version" records the last applied.
def _migrate_3(c: sqlite3.Connection) -> None:
    """Whisper confidence may be unknown (NaN from mlx_whisper); store it as NULL instead of failing the clip."""
    _run_script(
        c,
        """
        ALTER TABLE segments RENAME TO segments_v2;
        CREATE TABLE segments (
            clip_id TEXT NOT NULL REFERENCES clips(clip_id),
            seq INTEGER NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            text TEXT NOT NULL,
            avg_logprob REAL,
            no_speech_prob REAL,
            PRIMARY KEY (clip_id, seq)
        );
        INSERT INTO segments SELECT clip_id, seq, start_s, end_s, text, avg_logprob, no_speech_prob FROM segments_v2;
        DROP TABLE segments_v2;
        ALTER TABLE words RENAME TO words_v2;
        CREATE TABLE words (
            clip_id TEXT NOT NULL,
            segment_seq INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            word TEXT NOT NULL,
            probability REAL,
            PRIMARY KEY (clip_id, segment_seq, seq)
        );
        INSERT INTO words SELECT clip_id, segment_seq, seq, start_s, end_s, word, probability FROM words_v2;
        DROP TABLE words_v2;
        """,
    )


def _migrate_4(c: sqlite3.Connection) -> None:
    """Device state: the page key gains storage_instance; poll snapshots and sync runs."""
    _run_script(
        c,
        """
        ALTER TABLE pages RENAME TO pages_v3;
        CREATE TABLE pages (
            run INTEGER NOT NULL,
            "index" INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            capture_id INTEGER NOT NULL REFERENCES captures(id),
            session INTEGER NOT NULL,
            ingest_type INTEGER NOT NULL,
            absolute_ms INTEGER NOT NULL,
            storage_instance INTEGER NOT NULL DEFAULT 0,
            UNIQUE (storage_instance, run, "index", sha256)
        );
        INSERT INTO pages (run, "index", sha256, capture_id, session, ingest_type, absolute_ms)
            SELECT run, "index", sha256, capture_id, session, ingest_type, absolute_ms FROM pages_v3 ORDER BY rowid;
        DROP TABLE pages_v3;
        CREATE TABLE device_status (
            id INTEGER PRIMARY KEY, read_at_ms INTEGER NOT NULL, source TEXT NOT NULL,
            has_all_fields INTEGER NOT NULL, recording_state TEXT NOT NULL,
            oldest_page INTEGER NOT NULL, newest_page INTEGER NOT NULL,
            soc INTEGER NOT NULL, current_ma INTEGER NOT NULL, usb_state TEXT NOT NULL,
            firmware_ver TEXT NOT NULL, storage_instance INTEGER NOT NULL, charger_signal TEXT NOT NULL);
        CREATE INDEX device_status_read_at ON device_status(read_at_ms);
        CREATE TABLE sync_runs (
            id INTEGER PRIMARY KEY, started_ms INTEGER NOT NULL, ended_ms INTEGER,
            outcome TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', pages INTEGER NOT NULL DEFAULT 0,
            messages INTEGER NOT NULL DEFAULT 0, capture_id INTEGER REFERENCES captures(id),
            muted_by TEXT, unmute TEXT NOT NULL DEFAULT 'n/a', error TEXT);
        """,
    )


def _migrate_5(c: sqlite3.Connection) -> None:
    """Full-text index over transcript segments (standalone table; set_transcript keeps it in step)."""
    _run_script(
        c,
        """
        CREATE VIRTUAL TABLE segments_fts USING fts5(
            clip_id UNINDEXED, seq UNINDEXED, text, tokenize='unicode61 remove_diacritics 2');
        INSERT INTO segments_fts (clip_id, seq, text) SELECT clip_id, seq, text FROM segments;
        """,
    )


def _migrate_6(c: sqlite3.Connection) -> None:
    """Per-day Insights: one row per day, replaced on regeneration; the lists are JSON."""
    _run_script(
        c,
        """
        CREATE TABLE insights (
            day TEXT PRIMARY KEY, state TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            prompt_version INTEGER NOT NULL, generated_ms INTEGER NOT NULL, input_chars INTEGER NOT NULL,
            summary TEXT, follow_ups TEXT, people TEXT, topics TEXT, error TEXT);
        """,
    )


def _migrate_7(c: sqlite3.Connection) -> None:
    """Insights note whether the day's text was cut from the front to fit."""
    _run_script(c, "ALTER TABLE insights ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0;")


MIGRATIONS = [_migrate_1, _migrate_2, _migrate_3, _migrate_4, _migrate_5, _migrate_6, _migrate_7]

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


@dataclass(frozen=True)
class InsightRecord:
    day: date
    state: str  # done | error
    provider: str
    model: str
    prompt_version: int
    generated_ms: int
    input_chars: int
    insight: Optional[Insight]
    error: Optional[str]
    truncated: bool = False  # the day's text was cut from the front to fit


def _insight_record(r: sqlite3.Row) -> InsightRecord:
    insight = None
    if r["state"] == "done":
        ups = [FollowUp(f["text"], f["at_ms"], f["line_id"]) for f in json.loads(r["follow_ups"])]
        insight = Insight(r["summary"], ups, json.loads(r["people"]), json.loads(r["topics"]))
    return InsightRecord(date.fromisoformat(r["day"]), r["state"], r["provider"], r["model"], r["prompt_version"],
                         r["generated_ms"], r["input_chars"], insight, r["error"], bool(r["truncated"]))


class Database:
    def __init__(self, path: Path, timeout: float = 30.0):
        # the app's process thread and its actions write through separate connections: wait, don't fail
        self._conn = sqlite3.connect(str(path), timeout=timeout)
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
                f"state database schema version {current} is newer than this lavalier "
                f"supports ({len(MIGRATIONS)}); upgrade lavalier before using this state root"
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

    def capture_path(self, capture_id: int) -> str:
        return self._conn.execute("SELECT path FROM captures WHERE id = ?", (capture_id,)).fetchone()["path"]

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
        """Instance 0 means "unknown" (a CLI import has no device id), so it matches any instance
        on either side; two known instances must be equal."""
        instance = _u64_to_db(key.storage_instance)
        r = self._conn.execute(
            'SELECT 1 FROM pages WHERE run = ? AND "index" = ? AND sha256 = ? '
            "AND (storage_instance = ? OR storage_instance = 0 OR ? = 0)",
            (key.run, key.index, key.sha256, instance, instance),
        ).fetchone()
        return r is not None

    def page_owned_earlier(self, key: PageKey, capture_id: int) -> bool:
        """Whether a capture older than capture_id already registered this page, with the same
        instance-0 wildcard as page_seen."""
        instance = _u64_to_db(key.storage_instance)
        r = self._conn.execute(
            'SELECT 1 FROM pages WHERE run = ? AND "index" = ? AND sha256 = ? AND capture_id < ? '
            "AND (storage_instance = ? OR storage_instance = 0 OR ? = 0)",
            (key.run, key.index, key.sha256, capture_id, instance, instance),
        ).fetchone()
        return r is not None

    def pages_for_capture(self, capture_id: int) -> list[PageKey]:
        """The pages this capture registered first, in stream (insertion) order."""
        rows = self._conn.execute(
            'SELECT run, "index", sha256, storage_instance FROM pages WHERE capture_id = ? ORDER BY rowid',
            (capture_id,),
        ).fetchall()
        return [PageKey(r["run"], r["index"], r["sha256"], _u64_from_db(r["storage_instance"])) for r in rows]

    def add_page(self, key: PageKey, capture_id: int, session: int, ingest_type: int, absolute_ms: int) -> None:
        with self._write_scope():
            self._conn.execute(
                'INSERT INTO pages (run, "index", sha256, storage_instance, capture_id, session, ingest_type, absolute_ms) '
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (key.run, key.index, key.sha256, _u64_to_db(key.storage_instance), capture_id, session, ingest_type, absolute_ms),
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
            # Guard on the table's existence (one sqlite_master lookup): at schema 4 there is no index yet.
            indexed = self._has_table("segments_fts")
            if indexed:
                self._conn.execute("DELETE FROM segments_fts WHERE clip_id = ?", (clip_id,))
            for i, s in enumerate(t.segments):
                if indexed:
                    self._conn.execute(
                        "INSERT INTO segments_fts (clip_id, seq, text) VALUES (?, ?, ?)", (clip_id, i, s.text))
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

    def _has_table(self, name: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ? AND type = 'table'", (name,)).fetchone() is not None

    def search_segments(self, match: str, *, limit: int) -> list[sqlite3.Row]:
        """Best matches first, speech clips only (noise lines are never shown, so a hit there would lead
        nowhere); match is an FTS5 expression (search.fts_query shapes user text into one)."""
        return self._conn.execute(
            "SELECT f.clip_id, f.seq, snippet(segments_fts, 2, '<mark>', '</mark>', '…', 12) AS snippet, "
            "bm25(segments_fts) AS rank FROM segments_fts f JOIN clips c ON c.clip_id = f.clip_id "
            "WHERE segments_fts MATCH ? AND c.classification = 'speech' ORDER BY rank LIMIT ?",
            (match, limit)).fetchall()

    def segments_starting_between(self, clip_ids: list[str], day: date, from_ms: int,
                                  to_ms: int) -> list[sqlite3.Row]:
        """Segments of the day's transcribed clips among clip_ids whose wall-clock start is roughly within
        [from_ms, to_ms] (a millisecond of slack each side; the caller applies the exact bound). Rows
        carry clip_id, seq, start_s, text and the clip's first_ms; words are never read."""
        if not clip_ids:
            return []
        marks = ", ".join("?" * len(clip_ids))
        return self._conn.execute(
            "SELECT s.clip_id, s.seq, s.start_s, s.text, c.first_ms FROM segments s "
            "JOIN clips c ON c.clip_id = s.clip_id "
            f"WHERE s.clip_id IN ({marks}) AND c.day = ? AND c.transcript_text IS NOT NULL "
            "AND c.first_ms + s.start_s * 1000 BETWEEN ? AND ?",
            (*clip_ids, day.isoformat(), from_ms - 1, to_ms + 1)).fetchall()

    def segment_start_s(self, clip_id: str, seq: int) -> Optional[float]:
        r = self._conn.execute(
            "SELECT start_s FROM segments WHERE clip_id = ? AND seq = ?", (clip_id, seq)).fetchone()
        return None if r is None else r["start_s"]

    def transcript(self, clip_id: str, *, words: bool = True) -> Optional[Transcript]:
        """The clip's transcript; with words=False every segment's word list is empty and the words
        table is never read (the window and the day file need only segments)."""
        r = self._conn.execute(
            "SELECT transcript_text, language, model FROM clips WHERE clip_id = ?", (clip_id,)
        ).fetchone()
        if r is None or r["transcript_text"] is None:
            return None
        by_segment: dict[int, list[Word]] = {}
        for w in self._conn.execute(
            "SELECT * FROM words WHERE clip_id = ? ORDER BY segment_seq, seq", (clip_id,)
        ) if words else ():
            by_segment.setdefault(w["segment_seq"], []).append(
                Word(w["start_s"], w["end_s"], w["word"], w["probability"])
            )
        segments = [
            Segment(s["start_s"], s["end_s"], s["text"], s["avg_logprob"], s["no_speech_prob"],
                    by_segment.get(s["seq"], []))
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
                "INSERT INTO events (page_index, absolute_ms, type, payload, capture_id, day) VALUES (?, ?, ?, ?, ?, ?)",
                (e.page_index, e.absolute_ms, e.type, json.dumps(e.payload), e.capture_id,
                 e.day.isoformat() if e.day is not None else _local_date(e.absolute_ms)),
            )

    def events_for_day(self, day: date, types: Optional[list[str]] = None) -> list[EventRecord]:
        sql = "SELECT * FROM events WHERE day = ?"
        params: list = [day.isoformat()]
        if types is not None:
            sql += f" AND type IN ({', '.join('?' * len(types))})"
            params += types
        rows = self._conn.execute(sql + " ORDER BY absolute_ms, id", params).fetchall()
        return [
            EventRecord(r["page_index"], r["absolute_ms"], r["type"], json.loads(r["payload"]), r["capture_id"],
                        date.fromisoformat(r["day"]))
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

    def conversation(self, conversation_id: str) -> Optional[Conversation]:
        row = self._conn.execute("SELECT day FROM conversations WHERE conversation_id = ?",
                                 (conversation_id,)).fetchone()
        if row is None:
            return None
        day = date.fromisoformat(row["day"])
        return next((c for c in self.conversations_for_day(day) if c.conversation_id == conversation_id), None)

    def days_summary(self) -> list[sqlite3.Row]:
        """One row per day with clips, newest first: (day, speech_ms, conversations, stars, noise_clips).
        Speech is the speech clips' length (20 ms per chunk, as grouping counts it); stars are the day's
        short presses, attached or not."""
        return self._conn.execute(
            """
            SELECT d.day AS day,
                   (SELECT COALESCE(SUM(chunk_count * 20), 0) FROM clips
                     WHERE day = d.day AND classification = 'speech') AS speech_ms,
                   (SELECT COUNT(*) FROM conversations WHERE day = d.day) AS conversations,
                   (SELECT COUNT(*) FROM events
                     WHERE day = d.day AND type = 'button'
                       AND json_extract(payload, '$.button_event') = 'BUTTON_SHORT_PRESS') AS stars,
                   (SELECT COUNT(*) FROM clips WHERE day = d.day AND classification = 'noise') AS noise_clips
            FROM (SELECT DISTINCT day FROM clips) d
            ORDER BY d.day DESC
            """
        ).fetchall()

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

    # device status and sync runs

    def record_device_status(self, snap: DeviceSnapshot, *, source: str, charger_signal: str) -> int:
        with self._write_scope():
            cur = self._conn.execute(
                "INSERT INTO device_status (read_at_ms, source, has_all_fields, recording_state, oldest_page, "
                "newest_page, soc, current_ma, usb_state, firmware_ver, storage_instance, charger_signal) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snap.read_at_ms, source, int(snap.has_all_fields), snap.recording_state, snap.oldest_page,
                    snap.newest_page, snap.soc, snap.current_ma, snap.usb_state, snap.firmware_ver,
                    _u64_to_db(snap.storage_instance), charger_signal,
                ),
            )
            return int(cur.lastrowid)

    def latest_device_status(self) -> Optional[tuple[DeviceSnapshot, str, str]]:
        r = self._conn.execute("SELECT * FROM device_status ORDER BY read_at_ms DESC, id DESC LIMIT 1").fetchone()
        if r is None:
            return None
        snap = DeviceSnapshot(
            read_at_ms=r["read_at_ms"],
            has_all_fields=bool(r["has_all_fields"]),
            recording_state=r["recording_state"],
            oldest_page=r["oldest_page"],
            newest_page=r["newest_page"],
            soc=r["soc"],
            current_ma=r["current_ma"],
            usb_state=r["usb_state"],
            firmware_ver=r["firmware_ver"],
            storage_instance=_u64_from_db(r["storage_instance"]),
        )
        return snap, r["source"], r["charger_signal"]

    def start_sync_run(self, started_ms: int) -> int:
        with self._write_scope():
            cur = self._conn.execute(
                "INSERT INTO sync_runs (started_ms, outcome) VALUES (?, 'running')", (started_ms,)
            )
            return int(cur.lastrowid)

    def close_running_sync_runs(self, now_ms: int) -> int:
        """Rows still "running" belong to a process that died mid-sync; close them as interrupted."""
        with self._write_scope():
            cur = self._conn.execute(
                "UPDATE sync_runs SET outcome = 'error', error = 'interrupted', ended_ms = ? WHERE outcome = 'running'",
                (now_ms,))
            return cur.rowcount

    def finish_sync_run(
        self, run_id: int, *, ended_ms: int, outcome: str, reason: str, pages: int, messages: int,
        capture_id: Optional[int], muted_by: Optional[str], unmute: str, error: Optional[str],
    ) -> None:
        with self._write_scope():
            self._conn.execute(
                "UPDATE sync_runs SET ended_ms = ?, outcome = ?, reason = ?, pages = ?, messages = ?, "
                "capture_id = ?, muted_by = ?, unmute = ?, error = ? WHERE id = ?",
                (ended_ms, outcome, reason, pages, messages, capture_id, muted_by, unmute, error, run_id),
            )

    def last_sync_run(self) -> Optional[SyncRun]:
        r = self._conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
        if r is None:
            return None
        return SyncRun(
            id=r["id"], started_ms=r["started_ms"], ended_ms=r["ended_ms"], outcome=r["outcome"],
            reason=r["reason"], pages=r["pages"], messages=r["messages"], capture_id=r["capture_id"],
            muted_by=r["muted_by"], unmute=r["unmute"], error=r["error"],
        )

    def last_drain_ok_ms(self) -> Optional[int]:
        r = self._conn.execute("SELECT MAX(ended_ms) AS m FROM sync_runs WHERE outcome = 'drained'").fetchone()
        return r["m"]

    # insights

    def insight(self, day: date) -> Optional[InsightRecord]:
        r = self._conn.execute("SELECT * FROM insights WHERE day = ?", (day.isoformat(),)).fetchone()
        return _insight_record(r) if r else None

    def set_insight(self, day: date, *, provider: str, model: str, prompt_version: int, generated_ms: int,
                    input_chars: int, insight: Insight, truncated: bool = False) -> None:
        ups = [{"text": f.text, "at_ms": f.at_ms, "line_id": f.line_id} for f in insight.follow_ups]
        with self._write_scope():
            self._conn.execute(
                "INSERT OR REPLACE INTO insights (day, state, provider, model, prompt_version, generated_ms, "
                "input_chars, summary, follow_ups, people, topics, error, truncated) "
                "VALUES (?, 'done', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (day.isoformat(), provider, model, prompt_version, generated_ms, input_chars, insight.summary,
                 json.dumps(ups), json.dumps(insight.people), json.dumps(insight.topics), int(truncated)))

    def set_insight_error(self, day: date, *, provider: str, model: str, prompt_version: int, generated_ms: int,
                          input_chars: int, error: str, truncated: bool = False) -> None:
        with self._write_scope():
            self._conn.execute(
                "INSERT OR REPLACE INTO insights (day, state, provider, model, prompt_version, generated_ms, "
                "input_chars, summary, follow_ups, people, topics, error, truncated) "
                "VALUES (?, 'error', ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)",
                (day.isoformat(), provider, model, prompt_version, generated_ms, input_chars, error, int(truncated)))

    def insights_all(self) -> list[InsightRecord]:
        rows = self._conn.execute("SELECT * FROM insights WHERE state = 'done' ORDER BY day DESC").fetchall()
        return [_insight_record(r) for r in rows]

    def insight_counts(self) -> dict[str, int]:
        """Rows per state: {"done": n, "error": n}."""
        rows = self._conn.execute("SELECT state, COUNT(*) AS n FROM insights GROUP BY state").fetchall()
        counts = {"done": 0, "error": 0}
        counts.update({r["state"]: r["n"] for r in rows})
        return counts

    def day_text_chars(self) -> dict[date, int]:
        """An estimate, in one query, of each speech day's text size: the characters of its speech clips'
        segments. The day text sent to a model (times, speakers, the cut to fit) differs from it."""
        rows = self._conn.execute(
            "SELECT c.day AS day, SUM(LENGTH(s.text)) AS n FROM segments s JOIN clips c ON c.clip_id = s.clip_id "
            "WHERE c.classification = 'speech' GROUP BY c.day").fetchall()
        return {date.fromisoformat(r["day"]): int(r["n"] or 0) for r in rows}

    def days_with_speech(self) -> list[date]:
        rows = self._conn.execute(
            "SELECT DISTINCT day FROM clips WHERE classification = 'speech' ORDER BY day").fetchall()
        return [date.fromisoformat(r["day"]) for r in rows]

    # status

    def set_status(self, key: str, value: str) -> None:
        with self._write_scope():
            self._conn.execute("INSERT OR REPLACE INTO status (key, value) VALUES (?, ?)", (key, value))

    def clear_status(self, key: str) -> None:
        with self._write_scope():
            self._conn.execute("DELETE FROM status WHERE key = ?", (key,))

    def get_status(self, key: str) -> Optional[str]:
        r = self._conn.execute("SELECT value FROM status WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None
