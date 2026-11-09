"""Shared helpers for the Lambda functions in Account A and Account B."""
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator, List, Optional

import boto3
from botocore.config import Config

# CopyObject handles a single object of up to 5 GiB (larger needs multipart).
MAX_SINGLE_COPY_BYTES = 5 * 1024**3

ALLOWED_EXTENSIONS = {"pdf", "tif"}

# <LoanNumber>_<docType>_<date yyyymmdd>_<sequence>.<ext>
FILENAME_RE = re.compile(
    r"^(?P<loan>\d{1,20})_(?P<doc_type>[A-Za-z0-9]{1,20})_(?P<date>\d{8})_(?P<seq>\d{1,6})"
    r"\.(?P<ext>[A-Za-z0-9]{1,5})$"
)

# Folder names under the landing zone's Acquisition/ prefix that belong to the
# pipeline itself. An acquisition may not use one of these names.
RESERVED_FOLDERS = {"ERRORS", "MANIFEST", "TRIGGERS", "UNPROCESSED"}

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

THREAT_STATUS = "THREATS_FOUND"
SCAN_TAG = "GuardDutyMalwareScanStatus"


class TransientS3Error(Exception):
    """Throttling / 5xx style S3 errors. Step Functions retries this by name."""


@dataclass(frozen=True)
class Settings:
    intake_bucket: str
    landing_bucket: str
    intake_prefix: str
    landing_prefix: str
    work_prefix: str
    copy_manifest_prefix: str
    report_prefix: str
    chunk_size: int
    copy_threads: int


def settings() -> Settings:
    """Account A configuration, read from environment variables set by Terraform."""
    return Settings(
        intake_bucket=os.environ["INTAKE_BUCKET"],
        landing_bucket=os.environ["LANDING_BUCKET"],
        intake_prefix=os.environ.get("INTAKE_PREFIX", "partner-sftp/"),
        landing_prefix=os.environ.get("LANDING_PREFIX", "Acquisition/"),
        work_prefix=os.environ.get("WORK_PREFIX", "work/"),
        copy_manifest_prefix=os.environ.get("COPY_MANIFEST_PREFIX", "copy-manifests/"),
        report_prefix=os.environ.get("REPORT_PREFIX", "quarantine-reports/"),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "1000")),
        copy_threads=int(os.environ.get("COPY_THREADS", "32")),
    )


def s3_client():
    """S3 client with adaptive retries (automatic back-off on throttling)."""
    return boto3.client("s3", config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))


# --- validation of identifiers that end up in S3 keys ------------------------

def validate_name(value: str, what: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ValueError(f"Invalid {what}: {value!r}")
    return value


def validate_acquisition(value: str) -> str:
    validate_name(value, "acquisition")
    if value.upper() in RESERVED_FOLDERS:
        raise ValueError(f"Acquisition name {value!r} is reserved")
    return value


def validate_run_id(value: str) -> str:
    if not isinstance(value, str) or not _RUN_ID_RE.match(value):
        raise ValueError(f"Invalid run id: {value!r}")
    return value


# --- file names --------------------------------------------------------------

def parse_filename(name: str) -> Optional[dict]:
    """Return the parts of a valid file name, or None if the name is malformed."""
    m = FILENAME_RE.match(name)
    if not m:
        return None
    parts = m.groupdict()
    try:
        datetime.strptime(parts["date"], "%Y%m%d")
    except ValueError:
        return None
    parts["ext"] = parts["ext"].lower()
    return parts


def is_folder_marker(key: str) -> bool:
    """SFTP `mkdir` leaves a zero-byte object whose key ends with '/'."""
    return key.endswith("/")


# --- key layout ---------------------------------------------------------------

def intake_batch_prefix(cfg: Settings, acquisition: str, batch: str) -> str:
    return f"{cfg.intake_prefix}{acquisition}/{batch}/"


def work_base(cfg: Settings, acquisition: str, batch: str, run_id: str) -> str:
    return f"{cfg.work_prefix}{acquisition}/{batch}/{run_id}/"


def landing_key(cfg: Settings, acquisition: str, batch: str, loan: str, filename: str) -> str:
    return f"{cfg.landing_prefix}{acquisition}/{batch}/{loan}/{filename}"


def error_key(cfg: Settings, acquisition: str, batch: str, loan: str, filename: str) -> str:
    return f"{cfg.landing_prefix}ERRORS/{acquisition}/{batch}/{loan}/{filename}"


def manifest_dir(cfg: Settings, acquisition: str, batch: str, run_id: str) -> str:
    return f"{cfg.landing_prefix}MANIFEST/{acquisition}/{batch}/{run_id}/"


def copy_manifest_key(cfg: Settings, acquisition: str, batch: str, run_id: str) -> str:
    return f"{cfg.copy_manifest_prefix}{acquisition}/{batch}/{run_id}/copy-manifest.json"


# --- small S3 JSON helpers -----------------------------------------------------

def read_json(s3, bucket: str, key: str):
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def write_json(s3, bucket: str, key: str, payload) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
    )


def chunked(items: Iterable, size: int) -> Iterator[List]:
    batch: List = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
