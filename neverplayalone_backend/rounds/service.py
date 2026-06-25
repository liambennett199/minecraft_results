from __future__ import annotations

import hashlib

from neverplayalone_backend.api.config import BackendConfig
from neverplayalone_backend.api.store import BackendStore
from neverplayalone_backend.storage.service import ObjectStorageService
from neverplayalone_backend.utils.time import utc_now_ts


class RoundService:
    def __init__(self, store: BackendStore, storage: ObjectStorageService, config: BackendConfig):
        self.store = store
        self.storage = storage
        self.config = config

    def bootstrap_first_round(self, first_round_start_at: int | None = None) -> dict:
        existing = self.store.current_submission_round()
        if existing is not None:
            return existing
        start_at = first_round_start_at if first_round_start_at is not None else self.config.first_round_start_at
        if start_at is None:
            raise ValueError("first_round_start_at must be provided")
        return self._create_submission_round(
            submission_open_at=utc_now_ts(),
            evaluation_start_at=start_at,
        )

    def _create_submission_round(self, *, submission_open_at: int, evaluation_start_at: int) -> dict:
        return self.store.create_round(
            submission_open_at=submission_open_at,
            evaluation_start_at=evaluation_start_at,
            scoreboard_deadline_at=evaluation_start_at + self.config.scoreboard_deadline_offset_seconds,
            round_end_at=evaluation_start_at + self.config.round_duration_seconds,
            artifact_retention_rounds=self.config.artifact_retention_rounds,
        )

    def current_rounds(self) -> tuple[dict | None, dict | None]:
        self.store.mark_due_rounds_completed()
        return self.store.current_submission_round(), self.store.current_evaluating_round()

    def freeze_current_submission_round(self, *, round_id: int, freeze_block_hash: str) -> tuple[dict, dict]:
        round_row = self.store.get_round(round_id)
        if round_row is None:
            raise ValueError(f"unknown round_id {round_id}")
        if round_row["status"] != "submission_open":
            raise ValueError("round is not open for submissions")

        freeze_at = utc_now_ts()
        round_seed_hex = self._derive_round_seed_hex(freeze_block_hash)
        roster_entries = self.store.freeze_round_roster(round_id)
        roster_storage_key = self.storage.roster_storage_key(round_id=round_id)
        manifest = {
            "round_id": round_id,
            "freeze_block_hash": freeze_block_hash,
            "round_seed_hex": round_seed_hex,
            "mission_id": self.config.mission_id,
            "scoreboard_deadline_at": round_row["scoreboard_deadline_at"],
            "round_end_at": round_row["round_end_at"],
            "entries": [
                {
                    "miner_uid": row["miner_uid"],
                    "miner_hotkey": row["miner_hotkey"],
                    "submission_id": row["submission_id"],
                    "tarball_s3_key": row["storage_key"],
                    "sha256": row["sha256"],
                    "size_bytes": row["size_bytes"],
                }
                for row in roster_entries
            ],
        }
        self.storage.write_json(roster_storage_key, manifest)
        frozen_round = self.store.freeze_round(
            round_id=round_id,
            freeze_at=freeze_at,
            freeze_block_hash=freeze_block_hash,
            round_seed_hex=round_seed_hex,
            roster_storage_key=roster_storage_key,
        )
        if frozen_round is None:
            raise ValueError(f"unknown round_id {round_id}")

        self.store.mark_due_rounds_completed(now=freeze_at)
        next_round = self._create_submission_round(
            submission_open_at=freeze_at,
            evaluation_start_at=freeze_at + self.config.round_duration_seconds,
        )
        return frozen_round, next_round

    def public_round(self, round_id: int) -> dict:
        round_row = self.store.get_round(round_id)
        if round_row is None:
            raise ValueError(f"unknown round_id {round_id}")
        if utc_now_ts() < round_row["round_end_at"]:
            raise PermissionError("round is not public yet")
        return round_row

    @staticmethod
    def _derive_round_seed_hex(freeze_block_hash: str) -> str:
        normalized = freeze_block_hash.strip().lower()
        if normalized.startswith("0x"):
            normalized = normalized[2:]
        if not normalized:
            raise ValueError("freeze_block_hash must be non-empty")
        if all(ch in "0123456789abcdef" for ch in normalized):
            return normalized
        return hashlib.sha256(freeze_block_hash.encode("utf-8")).hexdigest()

