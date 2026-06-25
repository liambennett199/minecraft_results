from __future__ import annotations

import json
import math
import uuid

from fastapi import HTTPException

from neverplayalone_backend.api.models import (
    ConsensusUploadRequest,
    ConsensusUploadResponse,
    ScoreboardUploadRequest,
    ScoreboardUploadResponse,
)
from neverplayalone_backend.api.store import BackendStore
from neverplayalone_backend.storage.service import ObjectStorageService
from neverplayalone_backend.utils.time import utc_now_ts


class ScoreboardService:
    def __init__(self, store: BackendStore, storage: ObjectStorageService):
        self.store = store
        self.storage = storage

    def create_artifact_slot(
        self,
        *,
        round_id: int,
        validator_uid: int,
        validator_hotkey: str,
        miner_uid: int,
        miner_hotkey: str,
        artifact_kind: str,
        request_base_url: str,
    ):
        round_row = self.store.get_round(round_id)
        if round_row is None:
            raise HTTPException(404, f"unknown round_id {round_id}")
        if round_row["status"] != "evaluating":
            raise HTTPException(400, "artifacts can only be uploaded while the round is evaluating")
        return self.storage.create_upload_slot(
            store=self.store,
            storage_key=self.storage.artifact_storage_key(
                round_id=round_id,
                validator_hotkey=validator_hotkey,
                miner_hotkey=miner_hotkey,
                artifact_kind=artifact_kind,
            ),
            category=f"artifact:{artifact_kind}",
            request_base_url=request_base_url,
            owner_hotkey=validator_hotkey,
            metadata={
                "round_id": round_id,
                "validator_uid": validator_uid,
                "miner_uid": miner_uid,
                "miner_hotkey": miner_hotkey,
                "artifact_kind": artifact_kind,
            },
        )

    def validate_scoreboard(self, payload: ScoreboardUploadRequest) -> None:
        round_row = self.store.get_round(payload.round_id)
        if round_row is None:
            raise HTTPException(404, f"unknown round_id {payload.round_id}")
        if utc_now_ts() > round_row["scoreboard_deadline_at"]:
            raise HTTPException(400, "scoreboard deadline has passed")

        seen: set[str] = set()
        for row in payload.rows:
            if row.miner_hotkey in seen:
                raise HTTPException(400, "duplicate miner_hotkey in scoreboard rows")
            seen.add(row.miner_hotkey)
            if not math.isfinite(row.score):
                raise HTTPException(400, "score must be finite")
            if self.storage.stat_object(row.report_s3_key) is None:
                raise HTTPException(400, f"missing report artifact: {row.report_s3_key}")
            if self.storage.stat_object(row.recording_s3_key) is None:
                raise HTTPException(400, f"missing recording artifact: {row.recording_s3_key}")

    def store_scoreboard(self, *, validator_hotkey: str, payload: ScoreboardUploadRequest) -> ScoreboardUploadResponse:
        self.validate_scoreboard(payload)
        scoreboard_id = uuid.uuid4().hex
        created_at = utc_now_ts()
        storage_key = self.storage.scoreboard_storage_key(
            round_id=payload.round_id,
            validator_hotkey=validator_hotkey,
        )
        body = {
            "scoreboard_id": scoreboard_id,
            "round_id": payload.round_id,
            "validator_uid": payload.validator_uid,
            "validator_hotkey": validator_hotkey,
            "stake_weight": payload.stake_weight,
            "created_at": created_at,
            "rows": [row.model_dump(mode="json") for row in payload.rows],
        }
        self.storage.write_json(storage_key, body)
        self.store.store_scoreboard(
            scoreboard_id=scoreboard_id,
            round_id=payload.round_id,
            validator_uid=payload.validator_uid,
            validator_hotkey=validator_hotkey,
            stake_weight=payload.stake_weight,
            storage_key=storage_key,
            payload_json=json.dumps(body, separators=(",", ":"), sort_keys=True),
            created_at=created_at,
        )
        for row in payload.rows:
            self.store.store_validator_artifacts(
                round_id=payload.round_id,
                validator_uid=payload.validator_uid,
                validator_hotkey=validator_hotkey,
                miner_uid=row.miner_uid,
                miner_hotkey=row.miner_hotkey,
                report_s3_key=row.report_s3_key,
                recording_s3_key=row.recording_s3_key,
            )
        return ScoreboardUploadResponse(scoreboard_id=scoreboard_id, stored=True)

    def store_consensus_result(
        self,
        *,
        validator_hotkey: str,
        payload: ConsensusUploadRequest,
    ) -> ConsensusUploadResponse:
        round_row = self.store.get_round(payload.round_id)
        if round_row is None:
            raise HTTPException(404, f"unknown round_id {payload.round_id}")
        if utc_now_ts() > round_row["round_end_at"]:
            raise HTTPException(400, "round has already ended")

        consensus_result_id = uuid.uuid4().hex
        created_at = utc_now_ts()
        storage_key = self.storage.consensus_storage_key(
            round_id=payload.round_id,
            validator_hotkey=validator_hotkey,
        )
        body = {
            "consensus_result_id": consensus_result_id,
            "round_id": payload.round_id,
            "validator_uid": payload.validator_uid,
            "validator_hotkey": validator_hotkey,
            "top_miner_uid": payload.top_miner_uid,
            "top_miner_hotkey": payload.top_miner_hotkey,
            "created_at": created_at,
        }
        self.storage.write_json(storage_key, body)
        self.store.store_consensus_result(
            consensus_result_id=consensus_result_id,
            round_id=payload.round_id,
            validator_uid=payload.validator_uid,
            validator_hotkey=validator_hotkey,
            top_miner_uid=payload.top_miner_uid,
            top_miner_hotkey=payload.top_miner_hotkey,
            storage_key=storage_key,
            payload_json=json.dumps(body, separators=(",", ":"), sort_keys=True),
            created_at=created_at,
        )
        return ConsensusUploadResponse(consensus_result_id=consensus_result_id, stored=True)
