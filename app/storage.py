"""Reading audio in Cloudflare R2 (S3 API). The browser uploads and plays through presigned URLs, like
api-colegio-smart: the audio never goes through this service except when the worker analyzes it."""
import tempfile
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from app.settings import settings

EXTENSIONS = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav",
              "audio/mpeg": "mp3", "audio/x-m4a": "m4a"}


def extension(mime: str) -> str | None:
    return EXTENSIONS.get((mime or "").split(";")[0].strip().lower())


def new_key(institution_id: int, mime: str) -> str:
    # random key: the bucket must be private, but a guessable key would still be a risk if it is ever exposed
    return f"reading-audio/{institution_id}/{uuid.uuid4().hex}.{extension(mime) or 'webm'}"


@lru_cache(maxsize=1)
def _client():
    import boto3
    from botocore.config import Config

    if not (settings.r2_account_id and settings.r2_bucket):
        raise RuntimeError("Faltan R2_ACCOUNT_ID / R2_READING_BUCKET")
    return boto3.client(
        "s3", endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id, aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto", config=Config(signature_version="s3v4"))


def upload_url(key: str, mime: str) -> str:
    return _client().generate_presigned_url(
        "put_object", Params={"Bucket": settings.r2_bucket, "Key": key, "ContentType": mime},
        ExpiresIn=settings.presigned_ttl_seconds)


def download_url(key: str) -> str:
    return _client().generate_presigned_url(
        "get_object", Params={"Bucket": settings.r2_bucket, "Key": key}, ExpiresIn=settings.presigned_ttl_seconds)


def exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=settings.r2_bucket, Key=key)
        return True
    except Exception:
        return False


def download(key: str, folder: str) -> str:
    """Downloads the object to a file inside folder and returns its path (the worker deletes the folder)."""
    path = Path(folder) / Path(key).name
    _client().download_file(settings.r2_bucket, key, str(path))
    return str(path)


def upload_file(path: str, key: str, mime: str) -> None:
    _client().upload_file(path, settings.r2_bucket, key, ExtraArgs={"ContentType": mime})


def list_keys(prefix: str) -> list[tuple[str, datetime]]:
    """(key, last_modified) of every object under prefix."""
    keys = []
    for page in _client().get_paginator("list_objects_v2").paginate(Bucket=settings.r2_bucket, Prefix=prefix):
        keys += [(o["Key"], o["LastModified"]) for o in page.get("Contents", [])]
    return keys


def delete(key: str) -> None:
    _client().delete_object(Bucket=settings.r2_bucket, Key=key)


def temp_dir():
    return tempfile.TemporaryDirectory(prefix="lectura-")
