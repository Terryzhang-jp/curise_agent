"""Workspace Manager — file persistence, versioning, and restoration.

Manages the lifecycle of session workspace files:
- Sync generated files to Supabase Storage (persist across restarts)
- Restore persisted files when session resumes
- Version management (auto-versioned in manifest, old versions kept locally)
- List files for frontend display

Storage layout:
  {STORAGE_BUCKET}/workspace/{session_id}/{filename}
  {STORAGE_BUCKET}/workspace/{session_id}/_manifest.json
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# File types worth persisting (generated outputs)
PERSIST_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf"}

# Storage folder prefix for workspace files
STORAGE_FOLDER = "workspace"

# Manifest filename (tracks synced files and versions)
MANIFEST_FILE = "_workspace_manifest.json"


@dataclass
class FileVersion:
    """Tracks a single version of a file."""
    filename: str
    version: int
    storage_path: str
    size: int
    synced_at: float


@dataclass
class WorkspaceManifest:
    """Tracks all synced files and their versions for a session."""
    session_id: str
    files: dict[str, list[FileVersion]] = field(default_factory=dict)

    def latest_version(self, filename: str) -> int:
        return max((v.version for v in self.files.get(filename, [])), default=0)

    def add_version(self, fv: FileVersion):
        self.files.setdefault(fv.filename, []).append(fv)

    def all_latest_files(self) -> list[FileVersion]:
        """Get the latest version of each file."""
        result = []
        for versions in self.files.values():
            if versions:
                result.append(max(versions, key=lambda v: v.version))
        return result

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "files": {
                fname: [
                    {"filename": v.filename, "version": v.version,
                     "storage_path": v.storage_path, "size": v.size,
                     "synced_at": v.synced_at}
                    for v in versions
                ]
                for fname, versions in self.files.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorkspaceManifest:
        m = cls(session_id=data.get("session_id", ""))
        for fname, versions in data.get("files", {}).items():
            m.files[fname] = [FileVersion(**v) for v in versions]
        return m


def _load_manifest(workspace_dir: str) -> WorkspaceManifest:
    """Load manifest from local workspace directory."""
    path = os.path.join(workspace_dir, MANIFEST_FILE)
    if not os.path.exists(path):
        return WorkspaceManifest(session_id=os.path.basename(workspace_dir))
    try:
        with open(path, "r") as f:
            return WorkspaceManifest.from_dict(json.load(f))
    except Exception:
        return WorkspaceManifest(session_id=os.path.basename(workspace_dir))


def _save_manifest(workspace_dir: str, manifest: WorkspaceManifest):
    """Save manifest to local workspace + Supabase Storage."""
    # Save locally
    path = os.path.join(workspace_dir, MANIFEST_FILE)
    with open(path, "w") as f:
        json.dump(manifest.to_dict(), f, indent=2)

    # Also persist manifest to storage (for restore on server restart)
    try:
        from services.file_storage import storage as file_storage
        if file_storage.enabled:
            content = json.dumps(manifest.to_dict(), indent=2).encode("utf-8")
            file_storage.upload(
                STORAGE_FOLDER,
                f"{manifest.session_id}/{MANIFEST_FILE}",
                content,
                content_type="application/json",
            )
    except Exception as e:
        logger.debug("Could not persist manifest to storage: %s", e)


def sync_file_to_storage(
    session_id: str, workspace_dir: str, filename: str
) -> str | None:
    """Sync a single file from workspace to Supabase Storage.

    Handles versioning: tracks version history in manifest.
    Only uploads if file has changed (size-based check).

    Returns storage path if uploaded, None if skipped/failed.
    """
    from services.file_storage import storage as file_storage

    if not file_storage.enabled:
        return None

    filepath = os.path.join(workspace_dir, filename)
    if not os.path.isfile(filepath):
        return None

    ext = os.path.splitext(filename)[1].lower()
    if ext not in PERSIST_EXTENSIONS:
        return None

    manifest = _load_manifest(workspace_dir)
    current_version = manifest.latest_version(filename)
    file_size = os.path.getsize(filepath)

    # Skip if file hasn't changed (simple size check)
    existing = manifest.files.get(filename, [])
    if existing and existing[-1].size == file_size:
        return None

    new_version = current_version + 1

    # Keep old version locally with version suffix
    if current_version > 0 and os.path.exists(filepath):
        old_name = _versioned_name(filename, current_version)
        old_path = os.path.join(workspace_dir, old_name)
        if not os.path.exists(old_path):
            try:
                import shutil
                shutil.copy2(filepath, old_path)
            except Exception:
                pass  # Best-effort version backup

    # Upload
    storage_path = f"{STORAGE_FOLDER}/{session_id}/{filename}"
    try:
        with open(filepath, "rb") as f:
            content = f.read()

        content_types = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".csv": "text/csv",
            ".pdf": "application/pdf",
        }
        file_storage.upload(
            STORAGE_FOLDER,
            f"{session_id}/{filename}",
            content,
            content_type=content_types.get(ext, "application/octet-stream"),
        )

        fv = FileVersion(
            filename=filename,
            version=new_version,
            storage_path=storage_path,
            size=len(content),
            synced_at=time.time(),
        )
        manifest.add_version(fv)
        _save_manifest(workspace_dir, manifest)

        logger.info("Synced workspace file: %s (v%d, %d bytes)",
                     storage_path, new_version, len(content))
        return storage_path

    except Exception as e:
        logger.warning("Failed to sync workspace file %s: %s", filename, e)
        return None


def sync_workspace(session_id: str, workspace_dir: str) -> list[str]:
    """Scan workspace and sync all persistable files to Supabase Storage.

    Returns list of synced storage paths.
    """
    if not os.path.isdir(workspace_dir):
        return []

    synced = []
    for name in os.listdir(workspace_dir):
        if name.startswith("_") or name.startswith("."):
            continue
        path = sync_file_to_storage(session_id, workspace_dir, name)
        if path:
            synced.append(path)
    return synced


def restore_workspace(session_id: str, workspace_dir: str) -> list[str]:
    """Restore persisted files from Supabase Storage to workspace.

    Strategy: download manifest from storage → download each listed file
    that doesn't already exist locally.

    Returns list of restored filenames.
    """
    from services.file_storage import storage as file_storage

    if not file_storage.enabled:
        return []

    os.makedirs(workspace_dir, exist_ok=True)

    # 1. Download manifest from storage
    manifest_storage_path = f"{STORAGE_FOLDER}/{session_id}/{MANIFEST_FILE}"
    try:
        manifest_bytes = file_storage.download(manifest_storage_path)
        manifest = WorkspaceManifest.from_dict(json.loads(manifest_bytes))
    except (FileNotFoundError, Exception) as e:
        logger.debug("No workspace manifest in storage for %s: %s", session_id, e)
        return []

    # 2. Download each latest file that's missing locally
    restored = []
    for fv in manifest.all_latest_files():
        local_path = os.path.join(workspace_dir, fv.filename)
        if os.path.exists(local_path):
            continue  # Already exists locally, skip

        try:
            data = file_storage.download(fv.storage_path)
            with open(local_path, "wb") as f:
                f.write(data)
            restored.append(fv.filename)
            logger.info("Restored workspace file: %s (v%d, %d bytes)",
                         fv.filename, fv.version, len(data))
        except Exception as e:
            logger.warning("Failed to restore %s: %s", fv.filename, e)

    # 3. Save manifest locally
    if restored:
        _save_manifest(workspace_dir, manifest)

    return restored


def _versioned_name(filename: str, version: int) -> str:
    """Generate a versioned filename: inquiry.xlsx → inquiry_v1.xlsx"""
    base, ext = os.path.splitext(filename)
    return f"{base}_v{version}{ext}"


def list_workspace_files(session_id: str, workspace_dir: str) -> list[dict]:
    """List all files in workspace with version info."""
    if not os.path.isdir(workspace_dir):
        return []

    manifest = _load_manifest(workspace_dir)
    files = []

    for name in sorted(os.listdir(workspace_dir)):
        if name.startswith("_") or name.startswith("."):
            continue
        filepath = os.path.join(workspace_dir, name)
        if not os.path.isfile(filepath):
            continue

        ext = os.path.splitext(name)[1].lower()
        files.append({
            "filename": name,
            "size": os.path.getsize(filepath),
            "version": manifest.latest_version(name),
            "synced": bool(manifest.files.get(name)),
            "is_output": ext in PERSIST_EXTENSIONS,
            "modified_at": os.path.getmtime(filepath),
        })

    return files
