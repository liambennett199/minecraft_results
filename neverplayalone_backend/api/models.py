from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    owner_hotkey: str | None = None
    auth_disabled: bool


class RoundWindow(BaseModel):
    round_id: int
    status: str
    submission_open_at: int
    evaluation_start_at: int
    scoreboard_deadline_at: int
    round_end_at: int
    freeze_at: int | None = None
    freeze_block_hash: str | None = None
    round_seed_hex: str | None = None
    roster_storage_key: str | None = None
    artifact_retention_rounds: int


class CurrentRoundsResponse(BaseModel):
    submission_round: RoundWindow | None = None
    evaluating_round: RoundWindow | None = None


class MinerCurrentRoundResponse(BaseModel):
    submission_round: RoundWindow | None = None


class SubmissionSlotRequest(BaseModel):
    miner_uid: int
    filename: str = "agent.tar.gz"


class SubmissionSlotResponse(BaseModel):
    submission_id: str
    round_id: int
    miner_uid: int
    upload_url: str
    storage_key: str
    expires_at: int
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)


class SubmissionFinalizeRequest(BaseModel):
    submission_id: str


class SubmissionFinalizeResponse(BaseModel):
    submission_id: str
    round_id: int
    miner_uid: int
    miner_hotkey: str
    status: str
    accepted: bool
    sha256: str | None = None
    size_bytes: int | None = None
    rejection_reason: str | None = None


class RosterEntry(BaseModel):
    miner_uid: int
    miner_hotkey: str
    submission_id: str
    tarball_s3_key: str
    sha256: str
    size_bytes: int
    download_url: str | None = None


class RosterManifestResponse(BaseModel):
    round_id: int
    freeze_block_hash: str
    round_seed_hex: str
    mission_id: str
    scoreboard_deadline_at: int
    round_end_at: int
    entries: list[RosterEntry] = Field(default_factory=list)


class ValidatorArtifactSlotRequest(BaseModel):
    round_id: int
    validator_uid: int
    miner_uid: int
    miner_hotkey: str
    artifact_kind: Literal["report_json", "recording_mcpr"]


class ArtifactSlotResponse(BaseModel):
    upload_url: str
    storage_key: str
    expires_at: int
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)


class ScoreboardRow(BaseModel):
    miner_uid: int
    miner_hotkey: str
    score: float
    status: str
    report_s3_key: str
    recording_s3_key: str
    report_download_url: str | None = None
    recording_download_url: str | None = None


class ScoreboardUploadRequest(BaseModel):
    round_id: int
    validator_uid: int
    stake_weight: float
    rows: list[ScoreboardRow] = Field(default_factory=list)


class ScoreboardEnvelope(BaseModel):
    scoreboard_id: str
    round_id: int
    validator_uid: int
    validator_hotkey: str
    stake_weight: float
    storage_key: str
    created_at: int
    rows: list[ScoreboardRow] = Field(default_factory=list)


class ScoreboardUploadResponse(BaseModel):
    scoreboard_id: str
    stored: bool = True


class ConsensusUploadRequest(BaseModel):
    round_id: int
    validator_uid: int
    top_miner_uid: int
    top_miner_hotkey: str


class ConsensusUploadResponse(BaseModel):
    consensus_result_id: str
    stored: bool = True


class ConsensusEnvelope(BaseModel):
    consensus_result_id: str
    round_id: int
    validator_uid: int
    validator_hotkey: str
    top_miner_uid: int
    top_miner_hotkey: str
    storage_key: str
    created_at: int


class PublicRoundResponse(BaseModel):
    round: RoundWindow
    roster_download_url: str | None = None
    counts: dict[str, Any] = Field(default_factory=dict)


class AdminBootstrapRequest(BaseModel):
    first_round_start_at: int | None = None


class AdminFreezeRequest(BaseModel):
    freeze_block_hash: str


class AdminRoundResponse(BaseModel):
    round_id: int
    status: str
    next_round_id: int | None = None

