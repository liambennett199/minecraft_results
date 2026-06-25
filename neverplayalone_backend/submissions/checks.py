from __future__ import annotations

import io
import tarfile
from pathlib import PurePosixPath


def validate_submission_archive(payload: bytes, *, size_limit_bytes: int) -> tuple[str, int]:
    if len(payload) > size_limit_bytes:
        raise ValueError(f"submission exceeds size limit of {size_limit_bytes} bytes")
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            names: set[str] = set()
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"unsafe tar path: {member.name}")
                if member.issym() or member.islnk():
                    raise ValueError(f"link entries are not allowed: {member.name}")
                if member.isdev():
                    raise ValueError(f"device entries are not allowed: {member.name}")
                if member.isfile():
                    names.add(member.name)
            if "package.json" not in names:
                raise ValueError("agent archive must contain package.json at the archive root")
            if "index.js" not in names:
                raise ValueError("agent archive must contain index.js at the archive root")
    except tarfile.TarError as exc:
        raise ValueError("submission must be a valid .tar.gz archive") from exc
    return ("accepted", len(payload))
