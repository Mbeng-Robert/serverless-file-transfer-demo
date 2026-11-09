"""Copy pipeline, step 2: copy one chunk in parallel threads.

Valid files are copied into the landing zone, failed files into ERRORS/. The
source is never modified or deleted (copy, not move).
"""
from concurrent.futures import ThreadPoolExecutor

from botocore.exceptions import ClientError

from . import common as c

_TRANSIENT = {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "503", "500"}


def copy_one(s3, cfg, entry):
    """Return (outcome, detail). Raises TransientS3Error for retryable errors."""
    src, dst = entry["source_key"], entry["dest_key"]
    if entry.get("size", 0) > c.MAX_SINGLE_COPY_BYTES:
        return "failed", "ObjectTooLargeForSingleCopy"
    try:
        s3.copy_object(
            Bucket=cfg.landing_bucket,
            Key=dst,
            CopySource={"Bucket": cfg.intake_bucket, "Key": src},
            MetadataDirective="COPY",
            # Do not copy the source tags: that would need Get/PutObjectTagging
            # permissions, and the scanner's tags describe the intake copy only.
            TaggingDirective="REPLACE",
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            return "missing", code
        if code in ("AccessDenied", "403"):
            return "denied", code
        if code in _TRANSIENT:
            raise c.TransientS3Error(code) from exc
        return "failed", code
    return ("copied" if entry["action"] == "copy" else "quarantined"), ""


def handler(event, _context=None):
    cfg = c.settings()
    acquisition = c.validate_acquisition(event["acquisition"])
    batch = c.validate_name(event["batch"], "batch")
    run_id = c.validate_run_id(event["run_id"])
    chunk_key = event["chunk_key"]
    base = c.work_base(cfg, acquisition, batch, run_id)
    if not chunk_key.startswith(f"{base}copy/"):
        raise ValueError("chunk_key is outside this run's copy folder")
    s3 = c.s3_client()

    entries = c.read_json(s3, cfg.landing_bucket, chunk_key)
    with ThreadPoolExecutor(max_workers=cfg.copy_threads) as pool:
        outcomes = list(pool.map(lambda e: copy_one(s3, cfg, e), entries))

    result = {"copied": 0, "quarantined": 0, "missing": 0, "denied": 0, "failed": 0, "problems": []}
    for entry, (outcome, detail) in zip(entries, outcomes):
        result[outcome] += 1
        if outcome in ("missing", "denied", "failed"):
            result["problems"].append({"key": entry["source_key"], "outcome": outcome, "detail": detail})

    name = chunk_key.rsplit("/", 1)[-1]
    c.write_json(s3, cfg.landing_bucket, f"{base}copy-results/{name}", result)
    return {k: result[k] for k in ("copied", "quarantined", "missing", "denied", "failed")}
