from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from fastapi import HTTPException, Request

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_STORAGE_KEY = re.compile(r"^[0-9a-f]{32}\.(pdf|jpg|png|webp)$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ ()-]+")


def upload_root() -> Path:
    configured = os.environ.get("MYGYM_UPLOAD_DIR")
    root = Path(configured) if configured else Path.cwd() / ".data" / "mygym-uploads"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root.resolve()


def upload_path(storage_key: str) -> Path:
    if not _STORAGE_KEY.fullmatch(storage_key):
        raise HTTPException(status_code=404, detail="Upload not found")
    root = upload_root()
    path = (root / storage_key).resolve()
    if path.parent != root:
        raise HTTPException(status_code=404, detail="Upload not found")
    return path


def delete_upload(storage_key: str | None) -> None:
    if not storage_key or not _STORAGE_KEY.fullmatch(storage_key):
        return
    try:
        upload_path(storage_key).unlink(missing_ok=True)
    except OSError:
        pass


def _identify_file(payload: bytes) -> tuple[str, str] | None:
    if payload.startswith(b"%PDF-"):
        return "application/pdf", ".pdf"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _filename(request: Request) -> str:
    raw = unquote(request.headers.get("x-file-name", "upload"))
    normalized = raw.replace("\\", "/").split("/")[-1].strip().strip(".")
    safe = _SAFE_NAME.sub("_", normalized)[:160]
    return safe or "upload"


async def save_request_upload(
    request: Request, *, images_only: bool = False
) -> tuple[str, str, str, int]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail={"error": "File must be 10 MB or smaller", "code": "upload_too_large"},
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid upload length", "code": "invalid_upload"},
            ) from None

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail={"error": "File must be 10 MB or smaller", "code": "upload_too_large"},
            )
        chunks.append(chunk)

    payload = b"".join(chunks)
    detected = _identify_file(payload)
    if not detected or (images_only and not detected[0].startswith("image/")):
        raise HTTPException(
            status_code=415,
            detail={
                "error": "Upload a valid PDF, JPEG, PNG or WebP file",
                "code": "unsupported_upload_type",
            },
        )

    media_type, extension = detected
    storage_key = f"{uuid4().hex}{extension}"
    path = upload_path(storage_key)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
    except OSError:
        raise HTTPException(
            status_code=503,
            detail={"error": "Private file storage is unavailable", "code": "upload_storage_unavailable"},
        ) from None
    return storage_key, _filename(request), media_type, size
