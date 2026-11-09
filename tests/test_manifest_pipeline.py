import io

import pytest
from openpyxl import load_workbook

from conftest import ACQ, BATCH, INTAKE, LANDING, RUN, intake_key, put, put_clean_batch, put_folder_markers
from demo_pipeline import common as c
from demo_pipeline import merge_manifest, scan_batch, validate_chunk

EVENT = {"acquisition": ACQ, "batch": BATCH, "run_id": RUN}


def run_manifest(aws):
    scan = scan_batch.handler(EVENT)
    for chunk in scan["chunks"]:
        validate_chunk.handler({**EVENT, "chunk_key": chunk})
    return scan, merge_manifest.handler(EVENT)


def results(aws):
    cfg = c.settings()
    base = c.work_base(cfg, ACQ, BATCH, RUN)
    rows = []
    for obj in aws.list_objects_v2(Bucket=LANDING, Prefix=f"{base}validate/")["Contents"]:
        rows += c.read_json(aws, LANDING, obj["Key"])
    return {r["filename"]: r for r in rows}


def test_scan_counts_markers_and_chunks(aws):
    put_clean_batch(aws)
    out = scan_batch.handler(EVENT)
    assert out["listing"] == {"total_objects": 9, "folder_markers": 3, "real_files": 6, "zero_byte_files": 0}
    assert len(out["chunks"]) == 2  # 6 files, CHUNK_SIZE=4


def test_clean_batch_is_all_valid(aws):
    put_clean_batch(aws)
    _, summary = run_manifest(aws)
    assert summary["valid"] == 6 and summary["failed"] == 0
    assert summary["all_accounted_for"] is True


def test_each_validation_rule(aws):
    put_folder_markers(aws, ["1001", "1002"])
    put(aws, intake_key("1001", "1001_NOTE_20240115_001.pdf"))                  # good
    put(aws, intake_key("1001", "1001_NOTE_20240115_002.docx"))                 # bad extension
    put(aws, intake_key("1001", "notes.pdf"))                                    # bad filename
    put(aws, intake_key("1001", "1001_NOTE_20241345_001.pdf"))                  # impossible date
    put(aws, intake_key("1001", "9999_NOTE_20240115_003.pdf"))                  # loan != folder
    put(aws, intake_key("1002", "1002_DEED_20240115_001.pdf"))                  # kept
    put(aws, intake_key("1002", "1002_DEED_20240115_001.tif"))                  # duplicate id
    put(aws, intake_key("1002", "1002_APPR_20240115_001.pdf"), status="THREATS_FOUND")
    _, summary = run_manifest(aws)
    r = results(aws)
    assert r["1001_NOTE_20240115_001.pdf"]["status"] == "valid"
    assert r["1001_NOTE_20240115_002.docx"]["reasons"] == ["bad_extension"]
    assert "bad_filename" in r["notes.pdf"]["reasons"]
    assert "bad_filename" in r["1001_NOTE_20241345_001.pdf"]["reasons"]
    assert r["9999_NOTE_20240115_003.pdf"]["reasons"] == ["loan_folder_mismatch"]
    assert r["1002_DEED_20240115_001.pdf"]["status"] == "valid"
    assert r["1002_DEED_20240115_001.tif"]["reasons"] == ["duplicate"]
    assert r["1002_APPR_20240115_001.pdf"]["reasons"] == ["malware_threat"]
    assert summary["valid"] == 2 and summary["failed"] == 6


def test_only_threats_found_blocks_other_scan_states_pass_but_are_counted(aws):
    put_folder_markers(aws, ["1001"])
    put(aws, intake_key("1001", "1001_NOTE_20240115_001.pdf"), status="NOT_SCANNED")
    put(aws, intake_key("1001", "1001_NOTE_20240115_002.pdf"), status="UNKNOWN")
    put(aws, intake_key("1001", "1001_NOTE_20240115_003.pdf"), status=None)  # no tag at all
    _, summary = run_manifest(aws)
    assert summary["valid"] == 3
    assert summary["valid_but_unverified_scan"] == 3


def test_deliverables_are_written(aws):
    put_clean_batch(aws)
    put(aws, intake_key("1001", "bad.txt"))
    run_manifest(aws)
    cfg = c.settings()
    mdir = c.manifest_dir(cfg, ACQ, BATCH, RUN)
    body = aws.get_object(Bucket=LANDING, Key=f"{mdir}manifest.xlsx")["Body"].read()
    wb = load_workbook(io.BytesIO(body))
    assert wb.sheetnames == ["Summary", "Files", "Quarantine"]
    assert wb["Files"].max_row == 1 + 7
    assert wb["Quarantine"].max_row == 1 + 1
    report = aws.get_object(Bucket=INTAKE, Key=f"quarantine-reports/{ACQ}/{BATCH}/{RUN}.csv")["Body"].read().decode()
    assert "bad.txt" in report
    manifest = c.read_json(aws, LANDING, c.copy_manifest_key(cfg, ACQ, BATCH, RUN))
    actions = sorted({e["action"] for e in manifest["entries"]})
    assert actions == ["copy", "quarantine"]
    dests = {e["dest_key"] for e in manifest["entries"]}
    assert "Acquisition/ACQ01/BATCH001/1001/1001_NOTE_20240115_001.pdf" in dests
    assert "Acquisition/ERRORS/ACQ01/BATCH001/1001/bad.txt" in dests


def test_chunk_key_outside_run_is_refused(aws):
    put_clean_batch(aws)
    with pytest.raises(ValueError):
        validate_chunk.handler({**EVENT, "chunk_key": "work/other/scan/chunk-00001.json"})


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "ERRORS"])
def test_bad_acquisition_names_are_refused(aws, bad):
    with pytest.raises(ValueError):
        scan_batch.handler({**EVENT, "acquisition": bad})
