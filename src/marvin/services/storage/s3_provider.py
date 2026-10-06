"""S3-compatible storage provider (AWS S3, Cloudflare R2, MinIO, etc).

Registered from core as the ``s3`` storage plugin only until the ``marvin-storage-s3`` plugin takes it
over (slice 7 of the storage plan removes it, and boto3, from core).
"""

import hashlib
from collections.abc import Iterator, Mapping
from io import BytesIO
from typing import Any, BinaryIO

try:
    import boto3
    from botocore.exceptions import ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from marvin_integration_sdk.storage import Setting

from .base_provider import BaseStorageProvider, StorageMetadata


class S3StorageProvider(BaseStorageProvider):
    """
    Storage provider for S3-compatible object storage.

    Supports AWS S3, Cloudflare R2, MinIO, Backblaze B2, Wasabi, DigitalOcean Spaces, etc.
    """

    slug = "s3"
    settings = (
        Setting("STORAGE_S3_BUCKET", "Bucket", required=True),
        Setting("STORAGE_S3_REGION", "Region", default="auto"),
        Setting("STORAGE_S3_ENDPOINT", "Endpoint URL"),
        Setting("STORAGE_S3_ACCESS_KEY", "Access key ID"),
        Setting("STORAGE_S3_SECRET_KEY", "Secret access key", secret=True),
        Setting("STORAGE_REMOTE_PUBLIC_URL", "Public base URL"),
    )

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "S3StorageProvider":
        return cls(
            bucket=config["STORAGE_S3_BUCKET"],
            region=config.get("STORAGE_S3_REGION") or "auto",
            endpoint=config.get("STORAGE_S3_ENDPOINT"),
            access_key=config.get("STORAGE_S3_ACCESS_KEY"),
            secret_key=config.get("STORAGE_S3_SECRET_KEY"),
            public_base_url=config.get("STORAGE_REMOTE_PUBLIC_URL"),
        )

    def __init__(
        self,
        bucket: str,
        region: str = "auto",
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        public_base_url: str | None = None,
    ):
        """
        Initialize S3 storage provider.

        Args:
            bucket: S3 bucket name
            region: AWS region (use "auto" for Cloudflare R2)
            endpoint: Custom endpoint URL (for S3-compatible services)
            access_key: AWS access key ID
            secret_key: AWS secret access key
            public_base_url: Base URL for public access (CDN URL or bucket URL)
        """
        if not BOTO3_AVAILABLE:
            raise ImportError("boto3 is required for S3StorageProvider. Install it with: pip install boto3")

        self.bucket = bucket
        self.region = region
        self.endpoint = endpoint
        self.public_base_url = public_base_url

        # Initialize S3 client
        session_kwargs = {}
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key

        client_kwargs = {}
        if region:
            client_kwargs["region_name"] = region
        if endpoint:
            client_kwargs["endpoint_url"] = endpoint

        self.s3_client = boto3.client("s3", **session_kwargs, **client_kwargs)

    def put(
        self,
        storage_key: str,
        file_data: BinaryIO,
        content_type: str,
        metadata: dict | None = None,
    ) -> StorageMetadata:
        """Store a file in S3."""
        # Read file data and calculate checksum
        file_content = file_data.read()
        file_size = len(file_content)
        checksum = hashlib.sha256(file_content).hexdigest()

        # Prepare metadata
        extra_args: dict[str, Any] = {
            "ContentType": content_type,
        }
        if metadata:
            extra_args["Metadata"] = {k: str(v) for k, v in metadata.items()}

        # Upload to S3
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=storage_key,
            Body=file_content,
            **extra_args,
        )

        return StorageMetadata(
            storage_key=storage_key,
            size=file_size,
            content_type=content_type,
            checksum=checksum,
            metadata=metadata,
            checksum_algorithm="sha256",
        )

    def get(self, storage_key: str) -> BinaryIO:
        """Retrieve a file from S3."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=storage_key)
            return BytesIO(response["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"File not found: {storage_key}") from e
            raise

    def delete(self, storage_key: str) -> bool:
        """Delete a file from S3."""
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=storage_key)
            return True
        except ClientError:
            return False

    def exists(self, storage_key: str) -> bool:
        """Check if a file exists in S3."""
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=storage_key)
            return True
        except ClientError:
            return False

    def get_public_url(self, storage_key: str) -> str:
        """Get public URL for accessing a file."""
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{storage_key}"

        # Construct default S3 URL
        if self.endpoint:
            # For custom endpoints (R2, MinIO, etc), use endpoint URL
            endpoint_base = self.endpoint.rstrip("/")
            return f"{endpoint_base}/{self.bucket}/{storage_key}"
        else:
            # For AWS S3, use standard URL pattern
            return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{storage_key}"

    def get_metadata(self, storage_key: str) -> StorageMetadata:
        """Get metadata about a stored file."""
        try:
            response = self.s3_client.head_object(Bucket=self.bucket, Key=storage_key)

            return StorageMetadata(
                storage_key=storage_key,
                size=response["ContentLength"],
                content_type=response.get("ContentType", "application/octet-stream"),
                metadata=response.get("Metadata"),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise FileNotFoundError(f"File not found: {storage_key}") from e
            raise

    def iter_keys(self, prefix: str = "") -> Iterator[str]:
        """Every key under ``prefix`` (S3 lists in key order)."""
        for page in self.s3_client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield obj["Key"]

    def checksum(self, storage_key: str, algorithm: str = "sha256") -> str | None:
        """MD5 from a single-part ETag; anything else would need a download, so None."""
        if algorithm != "md5":
            return None
        try:
            etag = self.s3_client.head_object(Bucket=self.bucket, Key=storage_key).get("ETag", "").strip('"')
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"File not found: {storage_key}") from e
            raise
        return etag if etag and "-" not in etag else None
