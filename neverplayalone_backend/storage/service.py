from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from neverplayalone_backend.api.config import BackendConfig
from neverplayalone_backend.api.store import BackendStore
from neverplayalone_backend.utils.time import utc_now_ts


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class SlotEnvelope:
    upload_url: str
    storage_key: str
    expires_at: int
    method: str = "PUT"
    headers: dict[str, str] | None = None


class ObjectStorageService:
    def __init__(self, config: BackendConfig):
        self.config = config
        self.root = config.storage_root_abs()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, storage_key: str) -> Path:
        return self.root / storage_key

    def stat_object(self, storage_key: str) -> StoredObject | None:
        path = self._path_for_key(storage_key)
        if not path.exists():
            return None
        payload = path.read_bytes()
        return StoredObject(
            storage_key=storage_key,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def write_uploaded_bytes(self, storage_key: str, payload: bytes) -> StoredObject:
        path = self._path_for_key(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return StoredObject(
            storage_key=storage_key,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def write_json(self, storage_key: str, payload: dict) -> StoredObject:
        return self.write_uploaded_bytes(
            storage_key,
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        )

    def read_bytes(self, storage_key: str) -> bytes:
        return self._path_for_key(storage_key).read_bytes()

    def create_upload_slot(
        self,
        *,
        store: BackendStore,
        storage_key: str,
        category: str,
        request_base_url: str,
        owner_hotkey: str | None,
        metadata: dict,
    ) -> SlotEnvelope:
        token = uuid.uuid4().hex
        expires_at = utc_now_ts() + self.config.slot_ttl_seconds
        store.create_upload_slot(
            token=token,
            storage_key=storage_key,
            category=category,
            owner_hotkey=owner_hotkey,
            metadata_json=json.dumps(metadata, separators=(",", ":"), sort_keys=True),
            expires_at=expires_at,
        )
        return SlotEnvelope(
            upload_url=f"{request_base_url.rstrip('/')}/objects/upload/{token}",
            storage_key=storage_key,
            expires_at=expires_at,
            headers={},
        )

    def create_download_url(
        self,
        *,
        store: BackendStore,
        storage_key: str,
        request_base_url: str,
    ) -> str:
        token = uuid.uuid4().hex
        expires_at = utc_now_ts() + self.config.slot_ttl_seconds
        store.create_download_slot(token=token, storage_key=storage_key, expires_at=expires_at)
        return f"{request_base_url.rstrip('/')}/objects/download/{token}"

    def submission_storage_key(self, *, round_id: int, miner_hotkey: str, submission_id: str, filename: str) -> str:
        safe_name = os.path.basename(filename)
        return f"submissions/{round_id}/{miner_hotkey}/{submission_id}/{safe_name}"

    def roster_storage_key(self, *, round_id: int) -> str:
        return f"rounds/{round_id}/roster.json"

    def artifact_storage_key(
        self,
        *,
        round_id: int,
        validator_hotkey: str,
        miner_hotkey: str,
        artifact_kind: str,
    ) -> str:
        ext = "json" if artifact_kind == "report_json" else "mcpr"
        return f"artifacts/{round_id}/{validator_hotkey}/{miner_hotkey}/{artifact_kind}.{ext}"

    def scoreboard_storage_key(self, *, round_id: int, validator_hotkey: str) -> str:
        return f"scoreboards/{round_id}/{validator_hotkey}.json"

    def consensus_storage_key(self, *, round_id: int, validator_hotkey: str) -> str:
        return f"consensus/{round_id}/{validator_hotkey}.json"

