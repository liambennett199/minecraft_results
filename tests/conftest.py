from __future__ import annotations

import tarfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neverplayalone_backend.api.config import BackendConfig
from neverplayalone_backend.api.main import create_app


def build_agent_tarball() -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        package_json = b'{"name":"agent","version":"1.0.0"}'
        package_info = tarfile.TarInfo("package.json")
        package_info.size = len(package_json)
        archive.addfile(package_info, BytesIO(package_json))

        index_js = b'console.log("agent");\n'
        index_info = tarfile.TarInfo("index.js")
        index_info.size = len(index_js)
        archive.addfile(index_info, BytesIO(index_js))
    return buffer.getvalue()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = BackendConfig(
        db_path=str(tmp_path / "backend.db"),
        storage_root=str(tmp_path / "storage"),
        auth_disabled=True,
        owner_hotkey="owner-hotkey",
    )
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client
