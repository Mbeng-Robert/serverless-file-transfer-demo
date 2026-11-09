"""Manifest pipeline, step 3: merge validation results into the deliverables.

Writes, for one batch run:
  * an Excel manifest (MANIFEST/ in the landing zone)
  * a copy manifest (JSON) that the copy pipeline reads
  * a quarantine report (CSV, in the intake bucket)
"""
import csv
import io
from collections import Counter

from openpyxl import Workbook

from . import common as c


def _load_results(s3, cfg, base):
    results = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=cfg.landing_bucket, Prefix=f"{base}validate/"):
        for obj in page.get("Contents", []):
            results.extend(c.read_json(s3, cfg.landing_bucket, obj["Key"]))
    return sorted(results, key=lambda r: r["key"])


def _excel(acquisition, batch, run_id, summary, rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Acquisition", acquisition])
    ws.append(["Batch", batch])
    ws.append(["Run", run_id])
    for k, v in summary.items():
        if isinstance(v, dict):
            for rk, rv in sorted(v.items()):
                ws.append([f"{k}: {rk}", rv])
        else:
            ws.append([k, v])
    files = wb.create_sheet("Files")
    files.append(["key", "loan_folder", "filename", "size", "status", "reasons", "scan_status"])
    quarantine = wb.create_sheet("Quarantine")
    quarantine.append(["key", "loan_folder", "filename", "reasons"])
    for r in rows:
        files.append([r["key"], r["loan_folder"], r["filename"], r["size"], r["status"],
                      ",".join(r["reasons"]), r["scan_status"]])
        if r["status"] == "failed":
            quarantine.append([r["key"], r["loan_folder"], r["filename"], ",".join(r["reasons"])])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv(rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["key", "loan_folder", "filename", "reasons"])
    for r in rows:
        if r["status"] == "failed":
            w.writerow([r["key"], r["loan_folder"], r["filename"], ";".join(r["reasons"])])
    return buf.getvalue().encode("utf-8")


def handler(event, _context=None):
    cfg = c.settings()
    acquisition = c.validate_acquisition(event["acquisition"])
    batch = c.validate_name(event["batch"], "batch")
    run_id = c.validate_run_id(event["run_id"])
    s3 = c.s3_client()
    base = c.work_base(cfg, acquisition, batch, run_id)

    rows = _load_results(s3, cfg, base)
    listing = c.read_json(s3, cfg.landing_bucket, f"{base}scan/listing.json")

    reasons = Counter(reason for r in rows for reason in r["reasons"])
    valid = sum(1 for r in rows if r["status"] == "valid")
    summary = {
        "real_files_listed": listing["real_files"],
        "validated": len(rows),
        "valid": valid,
        "failed": len(rows) - valid,
        "failure_reasons": dict(reasons),
        "valid_but_unverified_scan": sum(
            1 for r in rows if r["status"] == "valid" and r["scan_status"] != "NO_MALWARE_FOUND"
        ),
        "folder_markers_ignored": listing["folder_markers"],
        "zero_byte_files": listing["zero_byte_files"],
        "all_accounted_for": len(rows) == listing["real_files"],
    }

    # Copy manifest: valid files go to the landing zone, failed ones to ERRORS/.
    entries = []
    for r in rows:
        loan = r["loan_folder"] or "_no_loan_folder"
        if r["status"] == "valid":
            dest = c.landing_key(cfg, acquisition, batch, loan, r["filename"])
            action = "copy"
        else:
            dest = c.error_key(cfg, acquisition, batch, loan, r["filename"])
            action = "quarantine"
        entries.append({"source_key": r["key"], "dest_key": dest, "action": action,
                        "size": r["size"], "reasons": r["reasons"]})
    c.write_json(
        s3, cfg.landing_bucket, c.copy_manifest_key(cfg, acquisition, batch, run_id),
        {"acquisition": acquisition, "batch": batch, "run_id": run_id, "entries": entries},
    )

    mdir = c.manifest_dir(cfg, acquisition, batch, run_id)
    s3.put_object(
        Bucket=cfg.landing_bucket, Key=f"{mdir}manifest.xlsx",
        Body=_excel(acquisition, batch, run_id, summary, rows),
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    c.write_json(s3, cfg.landing_bucket, f"{mdir}summary.json", summary)
    s3.put_object(
        Bucket=cfg.intake_bucket,
        Key=f"{cfg.report_prefix}{acquisition}/{batch}/{run_id}.csv",
        Body=_csv(rows), ContentType="text/csv",
    )
    return summary
