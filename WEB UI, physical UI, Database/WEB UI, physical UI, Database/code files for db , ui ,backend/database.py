"""
database.py — SQLite persistence layer for PotatoSort AI
Stores batch summaries and daily aggregate stats.
In-memory counters live in SharedState; this is called only on batch end or periodically.
"""

import sqlite3
import threading
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
#  SCHEMA
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Individual batch summary (one row per sorting session)
CREATE TABLE IF NOT EXISTS batches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      TEXT    NOT NULL UNIQUE,
    started_at    TEXT    NOT NULL,       -- ISO-8601
    ended_at      TEXT,
    duration_s    REAL    DEFAULT 0,
    speed         TEXT    NOT NULL,       -- HIGH | LOW
    cnt_large     INTEGER DEFAULT 0,
    cnt_medium    INTEGER DEFAULT 0,
    cnt_small     INTEGER DEFAULT 0,
    cnt_reject    INTEGER DEFAULT 0,
    cnt_total     INTEGER DEFAULT 0,
    reject_rate   REAL    DEFAULT 0,
    notes         TEXT,
    -- FIX (bug #2): "synced_*" remembers how much of this batch's counts
    -- have ALREADY been folded into daily_summary. save_batch() can be
    -- called more than once for the same batch_id (Save button mid-run,
    -- then Stop, then periodic auto-save) — without this, each call added
    -- the FULL running total again, double/triple-counting the daily
    -- totals. Now only the delta since the last save is added.
    synced_large  INTEGER DEFAULT 0,
    synced_medium INTEGER DEFAULT 0,
    synced_small  INTEGER DEFAULT 0,
    synced_reject INTEGER DEFAULT 0,
    -- FIX (bug #2, part 2): without this, daily_summary.batches_run would
    -- go up by 1 on EVERY save() call for the same batch_id (mid-run Save
    -- button + Stop + periodic auto-save = 3+ "batches" counted for one
    -- real batch). Now batches_run only increments the first time this
    -- batch_id is ever synced to daily_summary.
    daily_counted INTEGER DEFAULT 0
);

-- Daily aggregate (one row per calendar date)
CREATE TABLE IF NOT EXISTS daily_summary (
    summary_date  TEXT    PRIMARY KEY,    -- YYYY-MM-DD
    batches_run   INTEGER DEFAULT 0,
    cnt_large     INTEGER DEFAULT 0,
    cnt_medium    INTEGER DEFAULT 0,
    cnt_small     INTEGER DEFAULT 0,
    cnt_reject    INTEGER DEFAULT 0,
    cnt_total     INTEGER DEFAULT 0,
    avg_reject_pct REAL   DEFAULT 0,
    updated_at    TEXT
);

-- Fine-grained event log (optional — disable on low-storage devices)
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      TEXT    REFERENCES batches(batch_id),
    event_time    TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    message       TEXT,
    confidence    REAL,
    size_mm       REAL
);

-- Index for quick history queries
CREATE INDEX IF NOT EXISTS idx_batches_started ON batches(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_batch    ON events(batch_id);
"""


class Database:
    """
    Thread-safe SQLite wrapper using connection-per-thread pattern.
    SQLite connections cannot be shared across threads safely, so each
    thread gets its own connection via threading.local().
    """

    def __init__(self, db_path: str = "sorter.db"):
        self.db_path = db_path
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")  # Allows concurrent reads
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def init(self):
        """Create tables if they don't exist."""
        self._conn().executescript(SCHEMA_SQL)
        self._conn().commit()
        logger.info(f"Database ready: {self.db_path}")

    # ─────────────────────────────────────────────────────────── Batch ops

    def create_batch(self, batch_id: str, speed: str):
        """Insert a new batch row when sorting starts."""
        now = datetime.utcnow().isoformat()
        try:
            self._conn().execute(
                """
                INSERT OR IGNORE INTO batches (batch_id, started_at, speed)
                VALUES (?, ?, ?)
                """,
                (batch_id, now, speed),
            )
            self._conn().commit()
        except Exception as e:
            logger.error(f"create_batch error: {e}")

    def save_batch(
        self,
        batch_id: str,
        counts: dict,
        duration_s: float,
        speed: str,
        reject_rate: float,
        notes: Optional[str] = None,
    ):
        """
        Update batch row with the LATEST running/final counts.
        Safe to call multiple times for the same batch_id (Save button
        mid-run, then Stop, then periodic auto-save) — see FIX (bug #2)
        note on the schema above. Each call:
          1. Overwrites the batch row with the latest snapshot (cnt_* is
             always the true up-to-date total for that batch — fine to
             overwrite repeatedly).
          2. Adds only the DELTA (new potatoes since the previous save of
             THIS batch) into daily_summary, using the batch's own
             synced_* counters as the "already counted" watermark.
        """
        now = datetime.utcnow().isoformat()
        total = counts.get("large", 0) + counts.get("medium", 0) + \
            counts.get("small", 0) + counts.get("reject", 0)
        try:
            conn = self._conn()

            # ── Read the previous "already synced to daily_summary" watermark
            # for this batch. If the batch row doesn't exist yet, treat the
            # watermark as all-zero (nothing synced so far).
            cur = conn.execute(
                "SELECT synced_large, synced_medium, synced_small, synced_reject, daily_counted "
                "FROM batches WHERE batch_id = ?",
                (batch_id,),
            )
            row = cur.fetchone()
            prev_large  = row["synced_large"]  if row else 0
            prev_medium = row["synced_medium"] if row else 0
            prev_small  = row["synced_small"]  if row else 0
            prev_reject = row["synced_reject"] if row else 0
            # Has this batch_id EVER been synced to daily_summary before?
            # (0/None → first sync → this batch should count as +1 batch)
            already_counted = bool(row["daily_counted"]) if row else False

            # ── Delta = new potatoes counted since the last time THIS
            # batch was saved. Never negative in normal operation, but
            # clamp defensively in case of a counter reset mid-batch.
            delta = {
                "large":  max(0, counts.get("large", 0)  - prev_large),
                "medium": max(0, counts.get("medium", 0) - prev_medium),
                "small":  max(0, counts.get("small", 0)  - prev_small),
                "reject": max(0, counts.get("reject", 0) - prev_reject),
            }
            delta["total"] = delta["large"] + delta["medium"] + delta["small"] + delta["reject"]

            # ── Overwrite the batch row with the latest full snapshot, and
            # advance the synced_* watermark to the current counts so the
            # NEXT save only adds what's new after this point.
            conn.execute(
                """
                UPDATE batches
                SET ended_at      = ?,
                    duration_s    = ?,
                    speed         = ?,
                    cnt_large     = ?,
                    cnt_medium    = ?,
                    cnt_small     = ?,
                    cnt_reject    = ?,
                    cnt_total     = ?,
                    reject_rate   = ?,
                    notes         = ?,
                    synced_large  = ?,
                    synced_medium = ?,
                    synced_small  = ?,
                    synced_reject = ?,
                    daily_counted = 1
                WHERE batch_id = ?
                """,
                (
                    now, duration_s, speed,
                    counts.get("large", 0),
                    counts.get("medium", 0),
                    counts.get("small", 0),
                    counts.get("reject", 0),
                    total,
                    reject_rate,
                    notes,
                    counts.get("large", 0),
                    counts.get("medium", 0),
                    counts.get("small", 0),
                    counts.get("reject", 0),
                    batch_id,
                ),
            )
            conn.commit()

            # ── Only push the DELTA into daily_summary — this is the fix.
            # Previously the FULL running total was added every single
            # call, so pressing Save mid-run and then Stop would double
            # (or triple, with auto-save) count the same potatoes.
            # `increment_batch` is only True the FIRST time this batch_id
            # is synced, so batches_run counts real batches, not save calls.
            if delta["total"] > 0 or not already_counted:
                self._upsert_daily(delta, reject_rate, increment_batch=not already_counted)

            logger.info(
                f"Batch {batch_id} saved — {total} potatoes total "
                f"(+{delta['total']} new since last save)"
            )
        except Exception as e:
            logger.error(f"save_batch error: {e}")

    def _upsert_daily(self, counts: dict, reject_rate: float, increment_batch: bool = True):
        """
        Roll `counts` (now always a DELTA — see save_batch) into today's
        daily_summary row.

        FIX (bug #2, part 2): `increment_batch` lets the caller say whether
        this call represents a brand-new batch (True → bump batches_run) or
        a re-sync of a batch already counted once today (False → counts
        are folded in, but batches_run and the weighted average don't treat
        it as an extra batch). Without this, batches_run — and therefore
        avg_reject_pct, which is weighted by it — would drift upward every
        time the same batch was saved again.
        """
        today = date.today().isoformat()
        now = datetime.utcnow().isoformat()
        batch_increment = 1 if increment_batch else 0
        try:
            self._conn().execute(
                """
                INSERT INTO daily_summary
                    (summary_date, batches_run, cnt_large, cnt_medium, cnt_small,
                     cnt_reject, cnt_total, avg_reject_pct, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(summary_date) DO UPDATE SET
                    batches_run    = batches_run + ?,
                    cnt_large      = cnt_large  + excluded.cnt_large,
                    cnt_medium     = cnt_medium + excluded.cnt_medium,
                    cnt_small      = cnt_small  + excluded.cnt_small,
                    cnt_reject     = cnt_reject + excluded.cnt_reject,
                    cnt_total      = cnt_total  + excluded.cnt_total,
                    avg_reject_pct = CASE
                        -- Only fold reject_rate into the running average
                        -- when this call actually represents a new batch;
                        -- a mid-run resync of the SAME batch shouldn't
                        -- shift the average again.
                        WHEN ? = 1 THEN
                            (avg_reject_pct * batches_run + excluded.avg_reject_pct)
                            / (batches_run + 1)
                        ELSE avg_reject_pct
                    END,
                    updated_at     = excluded.updated_at
                """,
                (
                    today,
                    batch_increment,
                    counts.get("large", 0),
                    counts.get("medium", 0),
                    counts.get("small", 0),
                    counts.get("reject", 0),
                    counts.get("total", 0),
                    reject_rate,
                    now,
                    batch_increment,
                    batch_increment,
                ),
            )
            self._conn().commit()
        except Exception as e:
            logger.error(f"_upsert_daily error: {e}")

    # ─────────────────────────────────────────────────────────── Queries

    def get_recent_batches(self, n: int = 20) -> list[dict]:
        try:
            cur = self._conn().execute(
                """
                SELECT batch_id, started_at, ended_at, duration_s, speed,
                       cnt_large, cnt_medium, cnt_small, cnt_reject, cnt_total,
                       reject_rate, notes
                FROM batches
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (n,),
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"get_recent_batches error: {e}")
            return []

    def get_daily_summary(self, days: int = 7) -> list[dict]:
        try:
            cur = self._conn().execute(
                """
                SELECT summary_date, batches_run, cnt_total, cnt_reject,
                       avg_reject_pct, updated_at
                FROM daily_summary
                ORDER BY summary_date DESC
                LIMIT ?
                """,
                (days,),
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"get_daily_summary error: {e}")
            return []

    def get_batch(self, batch_id: str) -> Optional[dict]:
        try:
            cur = self._conn().execute(
                "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_batch error: {e}")
            return None
