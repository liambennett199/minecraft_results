from __future__ import annotations

import json

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from neverplayalone_backend.rounds.service import RoundService
from neverplayalone_backend.scoreboards.service import ScoreboardService
from neverplayalone_backend.storage.service import ObjectStorageService
from neverplayalone_backend.submissions.service import SubmissionService
from neverplayalone_backend.utils.time import utc_now_ts

from .auth import AuthContext, verify_miner, verify_owner, verify_validator
from .config import BackendConfig, load_config
from .models import (
    AdminBootstrapRequest,
    AdminFreezeRequest,
    AdminRoundResponse,
    ArtifactSlotResponse,
    ConsensusEnvelope,
    ConsensusUploadRequest,
    ConsensusUploadResponse,
    CurrentRoundsResponse,
    HealthResponse,
    MinerCurrentRoundResponse,
    PublicRoundResponse,
    RosterEntry,
    RosterManifestResponse,
    RoundWindow,
    ScoreboardEnvelope,
    ScoreboardUploadRequest,
    ScoreboardUploadResponse,
    SubmissionFinalizeRequest,
    SubmissionFinalizeResponse,
    SubmissionSlotRequest,
    SubmissionSlotResponse,
    ValidatorArtifactSlotRequest,
)
from .store import BackendStore


def _round_window(row: dict | None) -> RoundWindow | None:
    if row is None:
        return None
    return RoundWindow(
        round_id=row["round_id"],
        status=row["status"],
        submission_open_at=row["submission_open_at"],
        evaluation_start_at=row["evaluation_start_at"],
        scoreboard_deadline_at=row["scoreboard_deadline_at"],
        round_end_at=row["round_end_at"],
        freeze_at=row["freeze_at"],
        freeze_block_hash=row["freeze_block_hash"],
        round_seed_hex=row["round_seed_hex"],
        roster_storage_key=row["roster_storage_key"],
        artifact_retention_rounds=row["artifact_retention_rounds"],
    )


def create_app(config: BackendConfig | None = None) -> FastAPI:
    selected_config = config or load_config()
    store = BackendStore(selected_config)
    storage = ObjectStorageService(selected_config)
    round_service = RoundService(store, storage, selected_config)
    submission_service = SubmissionService(store, storage, selected_config)
    scoreboard_service = ScoreboardService(store, storage)

    app = FastAPI(title="Never Play Alone Backend")
    app.state.config = selected_config
    app.state.store = store
    app.state.storage = storage

    @app.on_event("startup")
    def _startup() -> None:
        store.init_db()
        store.cleanup_expired_slots()

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            owner_hotkey=selected_config.owner_hotkey or None,
            auth_disabled=selected_config.auth_disabled,
        )

    @app.get("/miner/rounds/current", response_model=MinerCurrentRoundResponse)
    def miner_current_round() -> MinerCurrentRoundResponse:
        submission_round, _ = round_service.current_rounds()
        return MinerCurrentRoundResponse(submission_round=_round_window(submission_round))

    @app.post("/miner/submissions/slot", response_model=SubmissionSlotResponse)
    def create_submission_slot(
        payload: SubmissionSlotRequest,
        request: Request,
        auth: AuthContext = Depends(verify_miner),
    ) -> SubmissionSlotResponse:
        try:
            return submission_service.create_submission_slot(
                miner_uid=payload.miner_uid,
                miner_hotkey=auth.hotkey,
                filename=payload.filename,
                request_base_url=str(request.base_url),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/miner/submissions/finalize", response_model=SubmissionFinalizeResponse)
    def finalize_submission(
        payload: SubmissionFinalizeRequest,
        auth: AuthContext = Depends(verify_miner),
    ) -> SubmissionFinalizeResponse:
        try:
            return submission_service.finalize_submission(
                submission_id=payload.submission_id,
                miner_hotkey=auth.hotkey,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/validator/rounds/current", response_model=CurrentRoundsResponse)
    def validator_current_rounds() -> CurrentRoundsResponse:
        submission_round, evaluating_round = round_service.current_rounds()
        return CurrentRoundsResponse(
            submission_round=_round_window(submission_round),
            evaluating_round=_round_window(evaluating_round),
        )

    @app.get("/validator/rounds/{round_id}/roster", response_model=RosterManifestResponse)
    def validator_round_roster(round_id: int, request: Request) -> RosterManifestResponse:
        round_row = store.get_round(round_id)
        if round_row is None:
            raise HTTPException(404, f"unknown round_id {round_id}")
        if not round_row["freeze_block_hash"] or not round_row["round_seed_hex"]:
            raise HTTPException(400, "round roster is not frozen yet")
        entries = [
            RosterEntry(
                miner_uid=row["miner_uid"],
                miner_hotkey=row["miner_hotkey"],
                submission_id=row["submission_id"],
                tarball_s3_key=row["storage_key"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                download_url=storage.create_download_url(
                    store=store,
                    storage_key=row["storage_key"],
                    request_base_url=str(request.base_url),
                ),
            )
            for row in store.list_round_roster(round_id)
        ]
        return RosterManifestResponse(
            round_id=round_id,
            freeze_block_hash=round_row["freeze_block_hash"],
            round_seed_hex=round_row["round_seed_hex"],
            mission_id=selected_config.mission_id,
            scoreboard_deadline_at=round_row["scoreboard_deadline_at"],
            round_end_at=round_row["round_end_at"],
            entries=entries,
        )

    @app.post("/validator/artifacts/slot", response_model=ArtifactSlotResponse)
    def validator_artifact_slot(
        payload: ValidatorArtifactSlotRequest,
        request: Request,
        auth: AuthContext = Depends(verify_validator),
    ) -> ArtifactSlotResponse:
        slot = scoreboard_service.create_artifact_slot(
            round_id=payload.round_id,
            validator_uid=payload.validator_uid,
            validator_hotkey=auth.hotkey,
            miner_uid=payload.miner_uid,
            miner_hotkey=payload.miner_hotkey,
            artifact_kind=payload.artifact_kind,
            request_base_url=str(request.base_url),
        )
        return ArtifactSlotResponse(
            upload_url=slot.upload_url,
            storage_key=slot.storage_key,
            expires_at=slot.expires_at,
            method=slot.method,
            headers=slot.headers or {},
        )

    @app.post("/validator/scoreboards", response_model=ScoreboardUploadResponse)
    def upload_scoreboard(
        payload: ScoreboardUploadRequest,
        auth: AuthContext = Depends(verify_validator),
    ) -> ScoreboardUploadResponse:
        return scoreboard_service.store_scoreboard(
            validator_hotkey=auth.hotkey,
            payload=payload,
        )

    @app.get("/validator/rounds/{round_id}/scoreboards", response_model=list[ScoreboardEnvelope])
    def list_scoreboards(round_id: int, request: Request) -> list[ScoreboardEnvelope]:
        if store.get_round(round_id) is None:
            raise HTTPException(404, f"unknown round_id {round_id}")
        envelopes: list[ScoreboardEnvelope] = []
        for row in store.list_round_scoreboards(round_id):
            payload = json.loads(row["payload_json"])
            envelopes.append(
                ScoreboardEnvelope(
                    scoreboard_id=row["scoreboard_id"],
                    round_id=row["round_id"],
                    validator_uid=row["validator_uid"],
                    validator_hotkey=row["validator_hotkey"],
                    stake_weight=row["stake_weight"],
                    storage_key=row["storage_key"],
                    created_at=row["created_at"],
                    rows=[
                        {
                            **score_row,
                            "report_download_url": storage.create_download_url(
                                store=store,
                                storage_key=score_row["report_s3_key"],
                                request_base_url=str(request.base_url),
                            ),
                            "recording_download_url": storage.create_download_url(
                                store=store,
                                storage_key=score_row["recording_s3_key"],
                                request_base_url=str(request.base_url),
                            ),
                        }
                        for score_row in payload["rows"]
                    ],
                )
            )
        return envelopes

    @app.post("/validator/consensus-results", response_model=ConsensusUploadResponse)
    def upload_consensus_result(
        payload: ConsensusUploadRequest,
        auth: AuthContext = Depends(verify_validator),
    ) -> ConsensusUploadResponse:
        return scoreboard_service.store_consensus_result(
            validator_hotkey=auth.hotkey,
            payload=payload,
        )

    @app.get("/public/rounds/{round_id}", response_model=PublicRoundResponse)
    def public_round(round_id: int, request: Request) -> PublicRoundResponse:
        try:
            round_row = round_service.public_round(round_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

        roster_download_url = None
        if round_row["roster_storage_key"]:
            roster_download_url = storage.create_download_url(
                store=store,
                storage_key=round_row["roster_storage_key"],
                request_base_url=str(request.base_url),
            )
        return PublicRoundResponse(
            round=_round_window(round_row),
            roster_download_url=roster_download_url,
            counts={
                "roster_entries": len(store.list_round_roster(round_id)),
                "scoreboards": len(store.list_round_scoreboards(round_id)),
                "consensus_results": len(store.list_consensus_results(round_id)),
            },
        )

    @app.get("/public/rounds/{round_id}/roster", response_model=RosterManifestResponse)
    def public_roster(round_id: int, request: Request) -> RosterManifestResponse:
        try:
            round_row = round_service.public_round(round_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        entries = [
            RosterEntry(
                miner_uid=row["miner_uid"],
                miner_hotkey=row["miner_hotkey"],
                submission_id=row["submission_id"],
                tarball_s3_key=row["storage_key"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                download_url=storage.create_download_url(
                    store=store,
                    storage_key=row["storage_key"],
                    request_base_url=str(request.base_url),
                ),
            )
            for row in store.list_round_roster(round_id)
        ]
        return RosterManifestResponse(
            round_id=round_id,
            freeze_block_hash=round_row["freeze_block_hash"],
            round_seed_hex=round_row["round_seed_hex"],
            mission_id=selected_config.mission_id,
            scoreboard_deadline_at=round_row["scoreboard_deadline_at"],
            round_end_at=round_row["round_end_at"],
            entries=entries,
        )

    @app.get("/public/rounds/{round_id}/scoreboards", response_model=list[ScoreboardEnvelope])
    def public_scoreboards(round_id: int, request: Request) -> list[ScoreboardEnvelope]:
        try:
            round_service.public_round(round_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        return list_scoreboards(round_id, request)

    @app.get("/public/rounds/{round_id}/consensus-results", response_model=list[ConsensusEnvelope])
    def public_consensus(round_id: int) -> list[ConsensusEnvelope]:
        try:
            round_service.public_round(round_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        return [
            ConsensusEnvelope(
                consensus_result_id=row["consensus_result_id"],
                round_id=row["round_id"],
                validator_uid=row["validator_uid"],
                validator_hotkey=row["validator_hotkey"],
                top_miner_uid=row["top_miner_uid"],
                top_miner_hotkey=row["top_miner_hotkey"],
                storage_key=row["storage_key"],
                created_at=row["created_at"],
            )
            for row in store.list_consensus_results(round_id)
        ]

    @app.post("/admin/bootstrap", response_model=AdminRoundResponse)
    def admin_bootstrap(
        payload: AdminBootstrapRequest,
        _: AuthContext = Depends(verify_owner),
    ) -> AdminRoundResponse:
        try:
            round_row = round_service.bootstrap_first_round(payload.first_round_start_at)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return AdminRoundResponse(round_id=round_row["round_id"], status=round_row["status"])

    @app.post("/admin/rounds/{round_id}/freeze", response_model=AdminRoundResponse)
    def admin_freeze_round(
        round_id: int,
        payload: AdminFreezeRequest,
        _: AuthContext = Depends(verify_owner),
    ) -> AdminRoundResponse:
        try:
            frozen_round, next_round = round_service.freeze_current_submission_round(
                round_id=round_id,
                freeze_block_hash=payload.freeze_block_hash,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return AdminRoundResponse(
            round_id=frozen_round["round_id"],
            status=frozen_round["status"],
            next_round_id=next_round["round_id"],
        )

    @app.put("/objects/upload/{token}")
    async def upload_object(token: str, request: Request) -> JSONResponse:
        row = store.get_upload_slot(token)
        if row is None:
            raise HTTPException(404, "unknown upload token")
        if row["consumed_at"] is not None:
            raise HTTPException(409, "upload token already consumed")
        if row["expires_at"] < utc_now_ts():
            raise HTTPException(410, "upload token expired")
        body = await request.body()
        stored = storage.write_uploaded_bytes(row["storage_key"], body)
        store.consume_upload_slot(token)
        return JSONResponse(
            {
                "stored": True,
                "storage_key": stored.storage_key,
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
            }
        )

    @app.get("/objects/download/{token}")
    def download_object(token: str) -> Response:
        row = store.get_download_slot(token)
        if row is None:
            raise HTTPException(404, "unknown download token")
        if row["expires_at"] < utc_now_ts():
            raise HTTPException(410, "download token expired")
        payload = storage.read_bytes(row["storage_key"])
        return Response(content=payload, media_type="application/octet-stream")

    return app


app = create_app()


def run() -> None:
    import uvicorn

    config = load_config()
    uvicorn.run(
        "neverplayalone_backend.api.main:app",
        host=config.api_host,
        port=config.api_port,
        log_level="info",
    )
