"""S3 storage helpers for AWS Textract pipeline."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from app.config import (
    AWS_REGION,
    AWS_S3_BUCKET,
    logger,
)


def _client():
    return boto3.client("s3", region_name=AWS_REGION)


def get_s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def upload_pdf_to_s3(*, exam_id: str, pdf_bytes: bytes, prefix: str = "textract") -> Dict[str, str]:
    """Upload PDF bytes to S3 and return S3 URI and key."""
    if not AWS_S3_BUCKET:
        raise ValueError("AWS_S3_BUCKET is not configured")
    if not pdf_bytes:
        raise ValueError("No PDF bytes provided")

    key = f"{prefix}/{exam_id}/{uuid.uuid4().hex}.pdf"
    client = _client()
    client.put_object(Bucket=AWS_S3_BUCKET, Key=key, Body=pdf_bytes, ContentType="application/pdf")

    logger.info("[AWS][S3] Uploaded PDF for exam %s to %s", exam_id, key)
    return {"bucket": AWS_S3_BUCKET, "key": key, "uri": get_s3_uri(AWS_S3_BUCKET, key)}


def upload_json_to_s3(*, key: str, payload: Dict[str, Any]) -> str:
    """Upload JSON payload to S3 and return URI."""
    if not AWS_S3_BUCKET:
        raise ValueError("AWS_S3_BUCKET is not configured")
    client = _client()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    client.put_object(
        Bucket=AWS_S3_BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    logger.info("[AWS][S3] Uploaded JSON to %s", key)
    return get_s3_uri(AWS_S3_BUCKET, key)


def download_json_from_s3(uri: str) -> Dict[str, Any]:
    """Download JSON payload from S3 URI."""
    if not uri.startswith("s3://"):
        raise ValueError("Invalid S3 URI")
    _, _, rest = uri.partition("s3://")
    bucket, _, key = rest.partition("/")
    client = _client()
    resp = client.get_object(Bucket=bucket, Key=key)
    data = resp["Body"].read()
    return json.loads(data.decode("utf-8"))


def build_raw_layer_key(exam_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"textract/raw/{exam_id}/raw_layer_{ts}.json"


def build_textract_source_key(exam_id: str, suffix: Optional[str] = None) -> str:
    tag = suffix or uuid.uuid4().hex
    return f"textract/source/{exam_id}/{tag}.pdf"

