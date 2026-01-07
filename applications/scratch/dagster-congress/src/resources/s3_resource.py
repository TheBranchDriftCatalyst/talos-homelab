"""S3/MinIO Dagster Resource."""

import os
from io import BytesIO
from typing import Any

import boto3
from botocore.config import Config
from dagster import ConfigurableResource


class S3Resource(ConfigurableResource):
    """
    Dagster resource for S3/MinIO storage.

    Used for storing intermediate pipeline data.
    """

    endpoint_url: str = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
    access_key: str = os.environ.get("S3_ACCESS_KEY", "minio")
    secret_key: str = os.environ.get("S3_SECRET_KEY", "minio123")
    bucket: str = os.environ.get("S3_BUCKET", "dagster-congress")
    region: str = "us-east-1"

    _client: Any = None

    @property
    def client(self):
        """Get or create S3 client."""
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def upload_json(self, key: str, data: dict | list) -> str:
        """Upload JSON data to S3."""
        import json

        body = json.dumps(data, default=str).encode("utf-8")
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        return f"s3://{self.bucket}/{key}"

    def download_json(self, key: str) -> dict | list:
        """Download JSON data from S3."""
        import json

        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload binary data to S3."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return f"s3://{self.bucket}/{key}"

    def download_bytes(self, key: str) -> bytes:
        """Download binary data from S3."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def list_objects(self, prefix: str = "") -> list[str]:
        """List objects with given prefix."""
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [obj["Key"] for obj in response.get("Contents", [])]

    def delete_object(self, key: str) -> None:
        """Delete an object."""
        self.client.delete_object(Bucket=self.bucket, Key=key)
