from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class BackendConfig:
    api_host: str = os.environ.get("NPA_API_HOST", "0.0.0.0")
    api_port: int = int(os.environ.get("NPA_API_PORT", "8000"))
    db_path: str = os.environ.get("NPA_DB_PATH", "npa_backend.db")
    storage_root: str = os.environ.get("NPA_STORAGE_ROOT", "storage")
    owner_hotkey: str = os.environ.get("NPA_OWNER_HOTKEY", "")
    auth_disabled: bool = os.environ.get("NPA_AUTH_DISABLED", "0").lower() in {"1", "true", "yes"}
    signature_max_age: int = int(os.environ.get("NPA_SIGNATURE_MAX_AGE_SECONDS", "300"))
    slot_ttl_seconds: int = int(os.environ.get("NPA_SLOT_TTL_SECONDS", "1800"))
    first_round_start_at: int | None = (
        int(os.environ["NPA_FIRST_ROUND_START_AT"]) if os.environ.get("NPA_FIRST_ROUND_START_AT") else None
    )
    round_duration_seconds: int = int(os.environ.get("NPA_ROUND_DURATION_SECONDS", "86400"))
    scoreboard_deadline_offset_seconds: int = int(
        os.environ.get("NPA_SCOREBOARD_DEADLINE_OFFSET_SECONDS", "43200")
    )
    artifact_retention_rounds: int = int(os.environ.get("NPA_ARTIFACT_RETENTION_ROUNDS", "5"))
    submission_size_limit_bytes: int = int(os.environ.get("NPA_SUBMISSION_SIZE_LIMIT_BYTES", "1000000"))
    mission_id: str = os.environ.get("NPA_MISSION_ID", "resource_gathering")

    def db_path_abs(self) -> Path:
        return Path(self.db_path).resolve()

    def storage_root_abs(self) -> Path:
        return Path(self.storage_root).resolve()


@lru_cache(maxsize=1)
def load_config() -> BackendConfig:
    return BackendConfig()

