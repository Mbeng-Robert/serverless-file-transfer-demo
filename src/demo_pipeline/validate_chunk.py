"""Manifest pipeline, step 2: validate one chunk of files (runs in parallel)."""
from botocore.exceptions import ClientError

from . import common as c

_TRANSIENT = {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "503", "500"}


def _scan_status(s3, bucket, key):
    """Return the malware scan tag value, or None if the object has no scan tag."""
    tags = s3.get_object_tagging(Bucket=bucket, Key=key)["TagSet"]
    for tag in tags:
        if tag["Key"] == c.SCAN_TAG:
            return tag["Value"]
    return None


def check_file(s3, cfg, rec):
    """Return (reasons, scan_status) for one file record."""
    reasons = []
    name = rec["filename"]

    if not rec["depth_ok"]:
        reasons.append("unexpected_folder_depth")

    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in c.ALLOWED_EXTENSIONS:
        reasons.append("bad_extension")

    parsed = c.parse_filename(name)
    if not parsed:
        reasons.append("bad_filename")
    elif parsed["loan"] != rec["loan_folder"]:
        reasons.append("loan_folder_mismatch")

    if rec["duplicate_of"]:
        reasons.append("duplicate")

    status = None
    try:
        status = _scan_status(s3, cfg.intake_bucket, rec["key"])
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            reasons.append("missing_from_intake")
        elif code in _TRANSIENT:
            raise c.TransientS3Error(code) from exc
        else:
            raise
    # Only THREATS_FOUND blocks a file. NOT_SCANNED / UNKNOWN / no tag pass, and are
    # counted separately so the gap is visible (see README).
    if status == c.THREAT_STATUS:
        reasons.append("malware_threat")
    return reasons, status


def handler(event, _context=None):
    cfg = c.settings()
    acquisition = c.validate_acquisition(event["acquisition"])
    batch = c.validate_name(event["batch"], "batch")
    run_id = c.validate_run_id(event["run_id"])
    chunk_key = event["chunk_key"]
    base = c.work_base(cfg, acquisition, batch, run_id)
    if not chunk_key.startswith(f"{base}scan/"):
        raise ValueError("chunk_key is outside this run's scan folder")
    s3 = c.s3_client()

    out = []
    for rec in c.read_json(s3, cfg.landing_bucket, chunk_key):
        reasons, status = check_file(s3, cfg, rec)
        out.append(
            {
                **rec,
                "scan_status": status or "NO_TAG",
                "status": "failed" if reasons else "valid",
                "reasons": reasons,
            }
        )
    name = chunk_key.rsplit("/", 1)[-1]
    c.write_json(s3, cfg.landing_bucket, f"{base}validate/{name}", out)
    valid = sum(1 for r in out if r["status"] == "valid")
    return {"files": len(out), "valid": valid, "failed": len(out) - valid}
