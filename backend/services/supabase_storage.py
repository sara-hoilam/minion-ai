"""Supabase Storage for project context files (server-side REST API)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from flask import current_app
from werkzeug.utils import secure_filename

from backend.config import (
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_STORAGE_BUCKET,
    SUPABASE_URL,
)

_memory_store: dict[str, bytes] = {}


class StorageNotConfiguredError(RuntimeError):
    pass


def storage_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _use_memory() -> bool:
    try:
        return current_app.config.get("TESTING") and not storage_configured()
    except RuntimeError:
        return not storage_configured()


def _storage_url(storage_path: str) -> str:
    base = SUPABASE_URL.rstrip("/")
    bucket = SUPABASE_STORAGE_BUCKET
    return f"{base}/storage/v1/object/{bucket}/{storage_path}"


def _request(method: str, url: str, data: bytes | None = None) -> bytes:
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
    }
    if data is not None:
        headers["Content-Type"] = "application/octet-stream"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=60) as resp:
            return resp.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Storage {method} failed ({exc.code}): {body}") from exc


def upload_project_file(user_id: int, project_id: int, filename: str, data: bytes) -> dict:
    safe = secure_filename(filename) or "file"
    storage_path = f"{user_id}/{project_id}/{uuid.uuid4().hex}_{safe}"

    if _use_memory():
        _memory_store[storage_path] = data
    else:
        _request("POST", _storage_url(storage_path), data)

    return {
        "filename": filename,
        "storage_path": storage_path,
        "size_bytes": len(data),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }


def download_project_file(storage_path: str) -> bytes:
    if _use_memory():
        if storage_path not in _memory_store:
            raise FileNotFoundError(storage_path)
        return _memory_store[storage_path]

    return _request("GET", _storage_url(storage_path))


def delete_project_file(storage_path: str) -> None:
    if _use_memory():
        _memory_store.pop(storage_path, None)
        return

    bucket = SUPABASE_STORAGE_BUCKET
    base = SUPABASE_URL.rstrip("/")
    url = f"{base}/storage/v1/object/{bucket}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Content-Type": "application/json",
    }
    payload = json.dumps({"prefixes": [storage_path]}).encode("utf-8")
    req = Request(url, data=payload, headers=headers, method="DELETE")
    try:
        with urlopen(req, timeout=60) as resp:
            resp.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Storage DELETE failed ({exc.code}): {body}") from exc


def clear_memory_store() -> None:
    _memory_store.clear()
