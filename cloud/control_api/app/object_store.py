"""Optional GCS persistence for campaign workspaces.

Cloud Run instances have ephemeral local disks, so when ``SERVO_GCS_BUCKET``
is configured every mutating request mirrors the campaign workspace into a
GCS bucket prefix and restores it before touching the files.  With the
variable unset the API behaves exactly as before (plain local directories),
which keeps tests and the local desktop workflow credential-free.

The module imports ``google-cloud-storage`` lazily; deployments that enable
the bucket must install it (see cloud/control_api/requirements-gcs.txt).
"""

from __future__ import annotations

import os
from pathlib import Path


def gcs_enabled() -> bool:
    return bool(os.environ.get("SERVO_GCS_BUCKET"))


def _client_and_prefix():
    if not gcs_enabled():
        return None, None
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError(
            "SERVO_GCS_BUCKET is set but google-cloud-storage is not installed"
        ) from exc
    client = storage.Client()
    bucket = client.bucket(os.environ["SERVO_GCS_BUCKET"])
    prefix = os.environ.get("SERVO_GCS_PREFIX", "campaigns").strip("/")
    return bucket, prefix


def _iter_workspace_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def sync_from_gcs(campaign_id: str, root: Path) -> None:
    """Restore the newest remote workspace state before local mutation."""

    bucket, prefix = _client_and_prefix()
    if bucket is None:
        return
    base = f"{prefix}/{campaign_id}"
    blobs = list(bucket.list_blobs(prefix=base))
    for blob in blobs:
        relative = blob.name[len(base):].lstrip("/")
        if not relative or relative.endswith("/"):
            continue
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target))


def sync_to_gcs(campaign_id: str, root: Path) -> None:
    """Mirror the workspace after a successful mutation."""

    bucket, prefix = _client_and_prefix()
    if bucket is None:
        return
    base = f"{prefix}/{campaign_id}"
    for path in _iter_workspace_files(root):
        blob = bucket.blob(f"{base}/{path.relative_to(root).as_posix()}")
        blob.upload_from_filename(str(path))
