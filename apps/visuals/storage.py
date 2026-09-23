"""Fajlovi u object storage-u (MinIO, S3 API). ADR-0018.

U bazi stoje samo metapodaci (`MediaAsset`); sam fajl je ovde. Ključ je
`personas/<ID>/<sha256>.<ext>`, pa ista slika nikada ne zauzme dva mesta.

Pristupni podaci se čitaju iz `.env.prod` preko `credential_ref`-a, kao i sve
ostale tajne — u bazi ih nema.
"""

from __future__ import annotations

import functools
import hashlib

from django.conf import settings

#: Šta smemo da upišemo. Sve ostalo se odbija pre poziva storage-a.
ALLOWED_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class StorageError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@functools.lru_cache(maxsize=1)
def _client():
    from apps.runtime.transport import CredentialMissing, resolve_secret

    try:
        import boto3
    except ImportError as e:  # pragma: no cover — zavisnost je u pyproject.toml
        raise StorageError("DEPENDENCY_MISSING", "boto3") from e
    try:
        key = resolve_secret(settings.S3_ACCESS_CREDENTIAL).strip()
        secret = resolve_secret(settings.S3_SECRET_CREDENTIAL).strip()
    except CredentialMissing as e:
        raise StorageError("CREDENTIAL_MISSING", str(e)) from e
    return boto3.client("s3", endpoint_url=settings.S3_ENDPOINT,
                        aws_access_key_id=key, aws_secret_access_key=secret,
                        region_name=settings.S3_REGION)


def reset_client() -> None:
    """Za testove i za promenu tajni bez restarta."""
    _client.cache_clear()


def key_for(public_id: str, digest: str, mime: str) -> str:
    persona = public_id.replace("-", "")
    return f"personas/{persona}/{digest[:32]}{ALLOWED_MIME[mime]}"


def put(data: bytes, *, key: str, mime: str) -> str:
    """Upisuje fajl i vraća ključ. Isti sadržaj na isti ključ je bezopasan."""
    if mime not in ALLOWED_MIME:
        raise StorageError("VALIDATION_ERROR", f"Nedozvoljen tip: {mime}")
    c = _client()
    try:
        c.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data, ContentType=mime)
    except Exception as e:  # noqa: BLE001 — botocore ima svoju hijerarhiju grešaka
        if "NoSuchBucket" in str(e):
            c.create_bucket(Bucket=settings.S3_BUCKET)
            c.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data, ContentType=mime)
        else:
            raise StorageError("STORAGE_WRITE", str(e)[:200]) from e
    return key


def get(key: str) -> bytes:
    try:
        return _client().get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read()
    except Exception as e:  # noqa: BLE001
        raise StorageError("STORAGE_READ", str(e)[:200]) from e


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
