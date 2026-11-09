"""Manifest pipeline, step 1: scan a batch in the intake bucket.

Lists intake/<acquisition>/<batch>/, skips SFTP folder markers, flags duplicates
(which needs a view of the whole batch), and writes the files to small chunk
files in S3 so the state machine only carries a short list of chunk keys.
"""
from . import common as c


def handler(event, _context=None):
    cfg = c.settings()
    acquisition = c.validate_acquisition(event["acquisition"])
    batch = c.validate_name(event["batch"], "batch")
    run_id = c.validate_run_id(event["run_id"])
    s3 = c.s3_client()

    prefix = c.intake_batch_prefix(cfg, acquisition, batch)
    base = c.work_base(cfg, acquisition, batch, run_id)

    records, markers, total_objects = [], 0, 0
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=cfg.intake_bucket, Prefix=prefix
    ):
        for obj in page.get("Contents", []):
            total_objects += 1
            key = obj["Key"]
            if c.is_folder_marker(key):
                markers += 1
                continue
            rel = key[len(prefix):]
            parts = rel.split("/")
            if len(parts) != 2:
                # not <loan>/<file>: still a real file, validation will quarantine it
                loan_folder, filename = (parts[0] if len(parts) > 1 else ""), parts[-1]
            else:
                loan_folder, filename = parts
            records.append(
                {
                    "key": key,
                    "size": obj["Size"],
                    "loan_folder": loan_folder,
                    "filename": filename,
                    "depth_ok": len(parts) == 2,
                    "duplicate_of": None,
                }
            )

    # Duplicate = same loan/docType/date/sequence seen more than once in the batch.
    # The first key (sorted) is kept, the others point at it.
    seen = {}
    for rec in sorted(records, key=lambda r: r["key"]):
        parsed = c.parse_filename(rec["filename"])
        if not parsed:
            continue
        ident = (parsed["loan"], parsed["doc_type"].lower(), parsed["date"], parsed["seq"])
        if ident in seen:
            rec["duplicate_of"] = seen[ident]
        else:
            seen[ident] = rec["key"]

    chunk_keys = []
    for n, part in enumerate(c.chunked(records, cfg.chunk_size), start=1):
        key = f"{base}scan/chunk-{n:05d}.json"
        c.write_json(s3, cfg.landing_bucket, key, part)
        chunk_keys.append(key)

    zero_byte = sum(1 for r in records if r["size"] == 0)
    listing = {
        "total_objects": total_objects,
        "folder_markers": markers,
        "real_files": len(records),
        "zero_byte_files": zero_byte,
    }
    c.write_json(s3, cfg.landing_bucket, f"{base}scan/listing.json", listing)
    return {"chunks": chunk_keys, "listing": listing}
