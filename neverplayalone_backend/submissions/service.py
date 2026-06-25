from __future__ import annotations

import hashlib
import os
import uuid

from neverplayalone_backend.api.config import BackendConfig
from neverplayalone_backend.api.models import SubmissionFinalizeResponse, SubmissionSlotResponse
from neverplayalone_backend.api.store import BackendStore
from neverplayalone_backend.storage.service import ObjectStorageService
from neverplayalone_backend.submissions.checks import validate_submission_archive
from neverplayalone_backend.utils.time import utc_now_ts


class SubmissionService:
    def __init__(self, store: BackendStore, storage: ObjectStorageService, config: BackendConfig):
        self.store = store
        self.storage = storage
        self.config = config

    def create_submission_slot(
        self,
        *,
        miner_uid: int,
        miner_hotkey: str,
        filename: str,
        request_base_url: str,
    ) -> SubmissionSlotResponse:
        round_row = self.store.current_submission_round()
        if round_row is None:
            raise ValueError("no submission round is currently open")
        if round_row["status"] != "submission_open":
            raise ValueError("submissions are not currently open")
        if not filename.endswith(".tar.gz"):
            raise ValueError("submission filename must end with .tar.gz")

        submission_id = uuid.uuid4().hex
        storage_key = self.storage.submission_storage_key(
            round_id=round_row["round_id"],
            miner_hotkey=miner_hotkey,
            submission_id=submission_id,
            filename=filename,
        )
        self.store.create_submission(
            submission_id=submission_id,
            round_id=round_row["round_id"],
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
            filename=filename,
            storage_key=storage_key,
            created_at=utc_now_ts(),
        )
        slot = self.storage.create_upload_slot(
            store=self.store,
            storage_key=storage_key,
            category="submission",
            request_base_url=request_base_url,
            owner_hotkey=miner_hotkey,
            metadata={
                "submission_id": submission_id,
                "round_id": round_row["round_id"],
                "miner_uid": miner_uid,
                "miner_hotkey": miner_hotkey,
            },
        )
        return SubmissionSlotResponse(
            submission_id=submission_id,
            round_id=round_row["round_id"],
            miner_uid=miner_uid,
            upload_url=slot.upload_url,
            storage_key=slot.storage_key,
            expires_at=slot.expires_at,
            method=slot.method,
            headers=slot.headers or {},
        )

    def finalize_submission(self, *, submission_id: str, miner_hotkey: str) -> SubmissionFinalizeResponse:
        row = self.store.get_submission(submission_id)
        if row is None:
            raise ValueError(f"unknown submission_id {submission_id}")
        if row["miner_hotkey"] != miner_hotkey:
            raise PermissionError("submission hotkey mismatch")

        round_row = self.store.get_round(row["round_id"])
        if round_row is None or round_row["status"] != "submission_open":
            raise ValueError("round is no longer open for submission finalization")

        stored = self.storage.stat_object(row["storage_key"])
        if stored is None:
            raise ValueError("uploaded submission object is missing")

        payload = self.storage.read_bytes(row["storage_key"])
        accepted = True
        rejection_reason = None
        try:
            validate_submission_archive(
                payload,
                size_limit_bytes=self.config.submission_size_limit_bytes,
            )
            status = "accepted"
        except ValueError as exc:
            accepted = False
            status = "rejected"
            rejection_reason = str(exc)

        finalized = self.store.finalize_submission(
            submission_id=submission_id,
            status=status,
            accepted=accepted,
            sha256=hashlib.sha256(payload).hexdigest() if accepted else None,
            size_bytes=len(payload) if accepted else None,
            rejection_reason=rejection_reason,
            finalized_at=utc_now_ts(),
        )
        return SubmissionFinalizeResponse(
            submission_id=finalized["submission_id"],
            round_id=finalized["round_id"],
            miner_uid=finalized["miner_uid"],
            miner_hotkey=finalized["miner_hotkey"],
            status=finalized["status"],
            accepted=bool(finalized["accepted"]),
            sha256=finalized["sha256"],
            size_bytes=finalized["size_bytes"],
            rejection_reason=finalized["rejection_reason"],
        )

