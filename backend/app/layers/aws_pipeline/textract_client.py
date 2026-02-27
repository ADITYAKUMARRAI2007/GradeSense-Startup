"""AWS Textract async client helpers."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import boto3

from app.config import (
    AWS_REGION,
    AWS_TEXTRACT_POLL_INTERVAL_SECS,
    AWS_TEXTRACT_POLL_TIMEOUT_SECS,
    AWS_TEXTRACT_ROLE_ARN,
    AWS_TEXTRACT_ENABLE_TABLES,
    logger,
)


def _client():
    return boto3.client("textract", region_name=AWS_REGION)


def start_document_analysis(*, bucket: str, key: str) -> str:
    """Start Textract async document analysis (TABLES + FORMS)."""
    client = _client()
    feature_types = ["FORMS"]
    if AWS_TEXTRACT_ENABLE_TABLES:
        feature_types = ["TABLES", "FORMS"]
    params: Dict[str, Any] = {
        "DocumentLocation": {"S3Object": {"Bucket": bucket, "Name": key}},
        "FeatureTypes": feature_types,
    }
    if AWS_TEXTRACT_ROLE_ARN:
        params["JobTag"] = "gradesense"
    response = client.start_document_analysis(**params)
    job_id = response.get("JobId")
    if not job_id:
        raise RuntimeError("Textract did not return JobId")
    logger.info("[AWS][Textract] Started analysis job %s", job_id)
    return job_id


def _fetch_blocks(job_id: str) -> List[Dict[str, Any]]:
    client = _client()
    blocks: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    while True:
        args: Dict[str, Any] = {"JobId": job_id}
        if next_token:
            args["NextToken"] = next_token
        resp = client.get_document_analysis(**args)
        blocks.extend(resp.get("Blocks") or [])
        next_token = resp.get("NextToken")
        if not next_token:
            break
    return blocks


def poll_document_analysis(job_id: str) -> Dict[str, Any]:
    """Poll Textract job until completion or timeout. Returns blocks + status."""
    client = _client()
    start = time.time()
    while True:
        resp = client.get_document_analysis(JobId=job_id)
        status = resp.get("JobStatus")
        if status in ("SUCCEEDED", "FAILED", "PARTIAL_SUCCESS"):
            logger.info("[AWS][Textract] Job %s status=%s", job_id, status)
            if status == "SUCCEEDED" or status == "PARTIAL_SUCCESS":
                blocks = _fetch_blocks(job_id)
                return {"status": status, "blocks": blocks}
            return {"status": status, "blocks": [], "error": resp.get("StatusMessage")}
        if time.time() - start > AWS_TEXTRACT_POLL_TIMEOUT_SECS:
            raise TimeoutError("Textract job timed out")
        time.sleep(AWS_TEXTRACT_POLL_INTERVAL_SECS)
