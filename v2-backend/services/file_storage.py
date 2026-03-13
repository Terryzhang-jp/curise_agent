"""Supabase Storage wrapper for persistent file storage.

Replaces local uploads/ directory which is ephemeral on Cloud Run.
Backward-compatible: download() falls back to local file for old /uploads/ paths.
"""

import logging
import os
import tempfile

from config import settings

logger = logging.getLogger(__name__)

BUCKET = settings.STORAGE_BUCKET
UPLOAD_DIR = settings.UPLOAD_DIR


class FileStorage:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from supabase import create_client
            self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        return self._client

    @property
    def enabled(self) -> bool:
        return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY)

    def upload(self, folder: str, filename: str, content: bytes,
               content_type: str = "application/octet-stream") -> str:
        """Upload file to Supabase Storage. Returns storage path like 'orders/abc.pdf'."""
        path = f"{folder}/{filename}"
        if not self.enabled:
            # Fallback: save locally
            local_path = os.path.join(UPLOAD_DIR, filename)
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(content)
            logger.warning("Supabase not configured, saved locally: %s", local_path)
            return f"/uploads/{filename}"

        self.client.storage.from_(BUCKET).upload(
            path, content, {"content-type": content_type, "upsert": "true"}
        )
        logger.info("Uploaded to storage: %s (%d bytes)", path, len(content))
        return path

    def download(self, storage_path: str) -> bytes:
        """Download file. Backward-compatible with old /uploads/ paths."""
        if not storage_path:
            raise FileNotFoundError("Empty storage path")

        # Backward compat: old local paths
        if storage_path.startswith("/uploads/"):
            local = os.path.join(UPLOAD_DIR, os.path.basename(storage_path))
            if os.path.exists(local):
                with open(local, "rb") as f:
                    return f.read()
            # Try Supabase with guessed path
            if self.enabled:
                basename = os.path.basename(storage_path)
                for folder in ("orders", "templates", "inquiries", "chat", "line", "attachments"):
                    try:
                        return self.client.storage.from_(BUCKET).download(f"{folder}/{basename}")
                    except Exception:
                        continue
            raise FileNotFoundError(f"File not found: {storage_path}")

        if not self.enabled:
            # Try local fallback
            local = os.path.join(UPLOAD_DIR, os.path.basename(storage_path))
            if os.path.exists(local):
                with open(local, "rb") as f:
                    return f.read()
            raise FileNotFoundError(f"File not found locally: {storage_path}")

        return self.client.storage.from_(BUCKET).download(storage_path)

    def download_to_temp(self, storage_path: str, suffix: str = ".xlsx") -> str:
        """Download to a temp file (for openpyxl). Caller must os.unlink() after use."""
        data = self.download(storage_path)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(data)
        tmp.close()
        return tmp.name

    def delete(self, storage_path: str):
        """Delete file from storage (best-effort)."""
        if not storage_path:
            return

        # Old local paths: delete locally
        if storage_path.startswith("/uploads/"):
            local = os.path.join(UPLOAD_DIR, os.path.basename(storage_path))
            if os.path.exists(local):
                try:
                    os.remove(local)
                except OSError:
                    pass
            return

        if not self.enabled:
            return
        try:
            self.client.storage.from_(BUCKET).remove([storage_path])
            logger.info("Deleted from storage: %s", storage_path)
        except Exception as e:
            logger.warning("Failed to delete %s: %s", storage_path, e)

    def get_signed_url(self, storage_path: str, expires_in: int = 3600) -> str:
        """Get a signed URL for temporary access."""
        if not self.enabled:
            return f"/uploads/{os.path.basename(storage_path)}"
        res = self.client.storage.from_(BUCKET).create_signed_url(storage_path, expires_in)
        return res.get("signedURL") or res.get("signedUrl", "")

    def ensure_bucket(self):
        """Ensure the storage bucket exists (call on startup)."""
        if not self.enabled:
            logger.warning("Supabase Storage not configured — using local uploads/ only")
            return
        try:
            self.client.storage.get_bucket(BUCKET)
            logger.info("Storage bucket '%s' exists", BUCKET)
        except Exception:
            try:
                self.client.storage.create_bucket(
                    BUCKET, options={"public": False, "file_size_limit": 50 * 1024 * 1024}
                )
                logger.info("Created storage bucket '%s'", BUCKET)
            except Exception as e:
                logger.warning("Could not create bucket '%s': %s", BUCKET, e)


storage = FileStorage()
