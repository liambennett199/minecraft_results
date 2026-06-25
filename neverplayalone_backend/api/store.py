from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from neverplayalone_backend.api.config import BackendConfig
from neverplayalone_backend.utils.time import utc_now_ts


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


class BackendStore:
    def __init__(self, config: BackendConfig):
        self.config = config
        self.db_path = config.db_path_abs()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = _dict_factory
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rounds (
                    round_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    submission_open_at INTEGER NOT NULL,
                    evaluation_start_at INTEGER NOT NULL,
                    scoreboard_deadline_at INTEGER NOT NULL,
                    round_end_at INTEGER NOT NULL,
                    freeze_at INTEGER,
                    freeze_block_hash TEXT,
                    round_seed_hex TEXT,
                    roster_storage_key TEXT,
                    artifact_retention_rounds INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id TEXT PRIMARY KEY,
                    round_id INTEGER NOT NULL,
                    miner_uid INTEGER NOT NULL,
                    miner_hotkey TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    sha256 TEXT,
                    size_bytes INTEGER,
                    rejection_reason TEXT,
                    created_at INTEGER NOT NULL,
                    finalized_at INTEGER,
                    replaced_by_submission_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_submissions_round_miner
                    ON submissions(round_id, miner_hotkey, created_at DESC);

                CREATE TABLE IF NOT EXISTS upload_slots (
                    token TEXT PRIMARY KEY,
                    storage_key TEXT NOT NULL,
                    category TEXT NOT NULL,
                    owner_hotkey TEXT,
                    metadata_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS download_slots (
                    token TEXT PRIMARY KEY,
                    storage_key TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scoreboards (
                    scoreboard_id TEXT PRIMARY KEY,
                    round_id INTEGER NOT NULL,
                    validator_uid INTEGER NOT NULL,
                    validator_hotkey TEXT NOT NULL,
                    stake_weight REAL NOT NULL,
                    storage_key TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scoreboards_round
                    ON scoreboards(round_id, validator_hotkey, created_at DESC);

                CREATE TABLE IF NOT EXISTS validator_artifacts (
                    round_id INTEGER NOT NULL,
                    validator_uid INTEGER NOT NULL,
                    validator_hotkey TEXT NOT NULL,
                    miner_uid INTEGER NOT NULL,
                    miner_hotkey TEXT NOT NULL,
                    report_s3_key TEXT NOT NULL,
                    recording_s3_key TEXT NOT NULL,
                    PRIMARY KEY (round_id, validator_hotkey, miner_hotkey)
                );

                CREATE TABLE IF NOT EXISTS consensus_results (
                    consensus_result_id TEXT PRIMARY KEY,
                    round_id INTEGER NOT NULL,
                    validator_uid INTEGER NOT NULL,
                    validator_hotkey TEXT NOT NULL,
                    top_miner_uid INTEGER NOT NULL,
                    top_miner_hotkey TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_consensus_round
                    ON consensus_results(round_id, validator_hotkey, created_at DESC);
                """
            )

    def cleanup_expired_slots(self, now: int | None = None) -> None:
        ts = utc_now_ts() if now is None else now
        with self.connect() as conn:
            conn.execute("DELETE FROM upload_slots WHERE expires_at < ?", (ts,))
            conn.execute("DELETE FROM download_slots WHERE expires_at < ?", (ts,))

    def create_round(
        self,
        *,
        submission_open_at: int,
        evaluation_start_at: int,
        scoreboard_deadline_at: int,
        round_end_at: int,
        artifact_retention_rounds: int,
    ) -> dict:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rounds (
                    status,
                    submission_open_at,
                    evaluation_start_at,
                    scoreboard_deadline_at,
                    round_end_at,
                    artifact_retention_rounds
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "submission_open",
                    submission_open_at,
                    evaluation_start_at,
                    scoreboard_deadline_at,
                    round_end_at,
                    artifact_retention_rounds,
                ),
            )
            return self.get_round(cursor.lastrowid, conn=conn)

    def get_round(self, round_id: int, *, conn: sqlite3.Connection | None = None) -> dict | None:
        manage = conn is None
        if manage:
            cm = self.connect()
            conn = cm.__enter__()
        try:
            row = conn.execute("SELECT * FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
            return row
        finally:
            if manage:
                cm.__exit__(None, None, None)

    def current_submission_round(self) -> dict | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM rounds WHERE status = 'submission_open' ORDER BY round_id DESC LIMIT 1"
            ).fetchone()

    def current_evaluating_round(self) -> dict | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM rounds WHERE status = 'evaluating' ORDER BY round_id DESC LIMIT 1"
            ).fetchone()

    def mark_due_rounds_completed(self, now: int | None = None) -> None:
        ts = utc_now_ts() if now is None else now
        with self.connect() as conn:
            conn.execute(
                "UPDATE rounds SET status = 'completed' WHERE status = 'evaluating' AND round_end_at <= ?",
                (ts,),
            )

    def freeze_round(
        self,
        *,
        round_id: int,
        freeze_at: int,
        freeze_block_hash: str,
        round_seed_hex: str,
        roster_storage_key: str,
    ) -> dict | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE rounds
                SET status = 'evaluating',
                    freeze_at = ?,
                    freeze_block_hash = ?,
                    round_seed_hex = ?,
                    roster_storage_key = ?
                WHERE round_id = ? AND status = 'submission_open'
                """,
                (freeze_at, freeze_block_hash, round_seed_hex, roster_storage_key, round_id),
            )
            return self.get_round(round_id, conn=conn)

    def create_submission(
        self,
        *,
        submission_id: str,
        round_id: int,
        miner_uid: int,
        miner_hotkey: str,
        filename: str,
        storage_key: str,
        created_at: int,
    ) -> dict:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    submission_id, round_id, miner_uid, miner_hotkey, filename, storage_key,
                    status, accepted, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    round_id,
                    miner_uid,
                    miner_hotkey,
                    filename,
                    storage_key,
                    "pending_upload",
                    0,
                    created_at,
                ),
            )
            return self.get_submission(submission_id, conn=conn)

    def get_submission(self, submission_id: str, *, conn: sqlite3.Connection | None = None) -> dict | None:
        manage = conn is None
        if manage:
            cm = self.connect()
            conn = cm.__enter__()
        try:
            return conn.execute(
                "SELECT * FROM submissions WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        finally:
            if manage:
                cm.__exit__(None, None, None)

    def finalize_submission(
        self,
        *,
        submission_id: str,
        status: str,
        accepted: bool,
        sha256: str | None,
        size_bytes: int | None,
        rejection_reason: str | None,
        finalized_at: int,
    ) -> dict:
        with self.connect() as conn:
            row = self.get_submission(submission_id, conn=conn)
            if row is None:
                raise ValueError(f"unknown submission_id {submission_id}")
            if accepted:
                active_rows = conn.execute(
                    """
                    SELECT submission_id FROM submissions
                    WHERE round_id = ? AND miner_hotkey = ? AND accepted = 1 AND replaced_by_submission_id IS NULL
                    """,
                    (row["round_id"], row["miner_hotkey"]),
                ).fetchall()
                for active in active_rows:
                    conn.execute(
                        "UPDATE submissions SET replaced_by_submission_id = ? WHERE submission_id = ?",
                        (submission_id, active["submission_id"]),
                    )
            conn.execute(
                """
                UPDATE submissions
                SET status = ?, accepted = ?, sha256 = ?, size_bytes = ?, rejection_reason = ?, finalized_at = ?
                WHERE submission_id = ?
                """,
                (
                    status,
                    1 if accepted else 0,
                    sha256,
                    size_bytes,
                    rejection_reason,
                    finalized_at,
                    submission_id,
                ),
            )
            return self.get_submission(submission_id, conn=conn)

    def freeze_round_roster(self, round_id: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM submissions
                WHERE round_id = ?
                  AND accepted = 1
                  AND replaced_by_submission_id IS NULL
                ORDER BY miner_uid ASC, miner_hotkey ASC
                """,
                (round_id,),
            ).fetchall()
            return rows

    def list_round_roster(self, round_id: int) -> list[dict]:
        return self.freeze_round_roster(round_id)

    def create_upload_slot(
        self,
        *,
        token: str,
        storage_key: str,
        category: str,
        owner_hotkey: str | None,
        metadata_json: str,
        expires_at: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO upload_slots (token, storage_key, category, owner_hotkey, metadata_json, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token, storage_key, category, owner_hotkey, metadata_json, expires_at),
            )

    def get_upload_slot(self, token: str) -> dict | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM upload_slots WHERE token = ?", (token,)).fetchone()

    def consume_upload_slot(self, token: str, consumed_at: int | None = None) -> None:
        ts = utc_now_ts() if consumed_at is None else consumed_at
        with self.connect() as conn:
            conn.execute("UPDATE upload_slots SET consumed_at = ? WHERE token = ?", (ts, token))

    def create_download_slot(self, *, token: str, storage_key: str, expires_at: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO download_slots (token, storage_key, expires_at) VALUES (?, ?, ?)",
                (token, storage_key, expires_at),
            )

    def get_download_slot(self, token: str) -> dict | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM download_slots WHERE token = ?", (token,)).fetchone()

    def store_scoreboard(
        self,
        *,
        scoreboard_id: str,
        round_id: int,
        validator_uid: int,
        validator_hotkey: str,
        stake_weight: float,
        storage_key: str,
        payload_json: str,
        created_at: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM scoreboards WHERE round_id = ? AND validator_hotkey = ?",
                (round_id, validator_hotkey),
            )
            conn.execute(
                """
                INSERT INTO scoreboards (
                    scoreboard_id, round_id, validator_uid, validator_hotkey,
                    stake_weight, storage_key, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scoreboard_id,
                    round_id,
                    validator_uid,
                    validator_hotkey,
                    stake_weight,
                    storage_key,
                    created_at,
                    payload_json,
                ),
            )

    def list_round_scoreboards(self, round_id: int) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM scoreboards WHERE round_id = ? ORDER BY validator_hotkey ASC",
                (round_id,),
            ).fetchall()

    def store_validator_artifacts(
        self,
        *,
        round_id: int,
        validator_uid: int,
        validator_hotkey: str,
        miner_uid: int,
        miner_hotkey: str,
        report_s3_key: str,
        recording_s3_key: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO validator_artifacts (
                    round_id, validator_uid, validator_hotkey, miner_uid, miner_hotkey,
                    report_s3_key, recording_s3_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    round_id,
                    validator_uid,
                    validator_hotkey,
                    miner_uid,
                    miner_hotkey,
                    report_s3_key,
                    recording_s3_key,
                ),
            )

    def store_consensus_result(
        self,
        *,
        consensus_result_id: str,
        round_id: int,
        validator_uid: int,
        validator_hotkey: str,
        top_miner_uid: int,
        top_miner_hotkey: str,
        storage_key: str,
        payload_json: str,
        created_at: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM consensus_results WHERE round_id = ? AND validator_hotkey = ?",
                (round_id, validator_hotkey),
            )
            conn.execute(
                """
                INSERT INTO consensus_results (
                    consensus_result_id, round_id, validator_uid, validator_hotkey,
                    top_miner_uid, top_miner_hotkey, storage_key, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    consensus_result_id,
                    round_id,
                    validator_uid,
                    validator_hotkey,
                    top_miner_uid,
                    top_miner_hotkey,
                    storage_key,
                    created_at,
                    payload_json,
                ),
            )

    def list_consensus_results(self, round_id: int) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM consensus_results WHERE round_id = ? ORDER BY validator_hotkey ASC",
                (round_id,),
            ).fetchall()

