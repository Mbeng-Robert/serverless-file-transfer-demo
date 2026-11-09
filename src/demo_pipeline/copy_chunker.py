"""Copy pipeline, steps 1 and 3: split the copy manifest into chunks, then summarise."""
from . import common as c


def handler(event, _context=None):
    """Read the copy manifest of a finished manifest run and write copy chunks."""
    cfg = c.settings()
    acquisition = c.validate_acquisition(event["acquisition"])
    batch = c.validate_name(event["batch"], "batch")
    run_id = c.validate_run_id(event["run_id"])
    manifest_run_id = c.validate_run_id(event["manifest_run_id"])
    s3 = c.s3_client()

    manifest = c.read_json(
        s3, cfg.landing_bucket, c.copy_manifest_key(cfg, acquisition, batch, manifest_run_id)
    )
    base = c.work_base(cfg, acquisition, batch, run_id)
    chunk_keys = []
    for n, part in enumerate(c.chunked(manifest["entries"], cfg.chunk_size), start=1):
        key = f"{base}copy/chunk-{n:05d}.json"
        c.write_json(s3, cfg.landing_bucket, key, part)
        chunk_keys.append(key)
    c.write_json(s3, cfg.landing_bucket, f"{base}copy/expected.json",
                 {"entries": len(manifest["entries"])})
    return {"chunks": chunk_keys, "entries": len(manifest["entries"])}


def summary_handler(event, _context=None):
    """Merge the copy results into one summary the operator can check."""
    cfg = c.settings()
    acquisition = c.validate_acquisition(event["acquisition"])
    batch = c.validate_name(event["batch"], "batch")
    run_id = c.validate_run_id(event["run_id"])
    s3 = c.s3_client()
    base = c.work_base(cfg, acquisition, batch, run_id)

    expected = c.read_json(s3, cfg.landing_bucket, f"{base}copy/expected.json")["entries"]
    totals = {"copied": 0, "quarantined": 0, "missing": 0, "denied": 0, "failed": 0}
    failures = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=cfg.landing_bucket, Prefix=f"{base}copy-results/"
    ):
        for obj in page.get("Contents", []):
            result = c.read_json(s3, cfg.landing_bucket, obj["Key"])
            for k in totals:
                totals[k] += result[k]
            failures.extend(result["problems"])

    accounted = sum(totals.values())
    summary = {
        "expected": expected,
        **totals,
        "all_accounted_for": accounted == expected,
        "clean": accounted == expected and not (totals["missing"] + totals["denied"] + totals["failed"]),
    }
    key = f"{cfg.copy_manifest_prefix}{acquisition}/{batch}/{run_id}/copy-summary.json"
    c.write_json(s3, cfg.landing_bucket, key, {**summary, "problems": failures})
    return summary
