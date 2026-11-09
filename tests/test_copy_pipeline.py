import pytest
from botocore.exceptions import ClientError

from conftest import ACQ, BATCH, COPY_RUN, INTAKE, LANDING, RUN, intake_key, put, put_clean_batch
from demo_pipeline import common as c
from demo_pipeline import copy_chunker, copy_files, merge_manifest, scan_batch, validate_chunk

MANIFEST_EVENT = {"acquisition": ACQ, "batch": BATCH, "run_id": RUN}
COPY_EVENT = {"acquisition": ACQ, "batch": BATCH, "run_id": COPY_RUN, "manifest_run_id": RUN}


def build_manifest():
    scan = scan_batch.handler(MANIFEST_EVENT)
    for chunk in scan["chunks"]:
        validate_chunk.handler({**MANIFEST_EVENT, "chunk_key": chunk})
    merge_manifest.handler(MANIFEST_EVENT)


def run_copy():
    chunked = copy_chunker.handler(COPY_EVENT)
    for chunk in chunked["chunks"]:
        copy_files.handler({**COPY_EVENT, "chunk_key": chunk})
    return chunked, copy_chunker.summary_handler(COPY_EVENT)


def landing_keys(aws, prefix="Acquisition/"):
    out = []
    for page in aws.get_paginator("list_objects_v2").paginate(Bucket=LANDING, Prefix=prefix):
        out += [o["Key"] for o in page.get("Contents", [])]
    return out


def test_valid_files_land_and_failed_files_go_to_errors(aws):
    put_clean_batch(aws)
    put(aws, intake_key("1001", "bad.txt"))
    build_manifest()
    _, summary = run_copy()
    assert summary["copied"] == 6 and summary["quarantined"] == 1
    assert summary["all_accounted_for"] and summary["clean"]
    keys = landing_keys(aws)
    assert "Acquisition/ACQ01/BATCH001/1002/1002_DEED_20240115_002.pdf" in keys
    assert "Acquisition/ERRORS/ACQ01/BATCH001/1001/bad.txt" in keys


def test_source_is_never_changed(aws):
    put_clean_batch(aws)
    before = sorted(o["Key"] for o in aws.list_objects_v2(Bucket=INTAKE, Prefix="partner-sftp/")["Contents"])
    build_manifest()
    run_copy()
    after = sorted(o["Key"] for o in aws.list_objects_v2(Bucket=INTAKE, Prefix="partner-sftp/")["Contents"])
    assert before == after


def test_source_scan_tags_are_not_copied(aws):
    put_clean_batch(aws)
    build_manifest()
    run_copy()
    tags = aws.get_object_tagging(
        Bucket=LANDING, Key="Acquisition/ACQ01/BATCH001/1001/1001_NOTE_20240115_001.pdf")["TagSet"]
    assert tags == []


def test_file_removed_after_manifest_is_reported_missing(aws):
    put_clean_batch(aws)
    build_manifest()
    aws.delete_object(Bucket=INTAKE, Key=intake_key("1001", "1001_NOTE_20240115_001.pdf"))
    _, summary = run_copy()
    assert summary["missing"] == 1 and summary["copied"] == 5
    assert summary["all_accounted_for"] and not summary["clean"]


def test_rerun_is_idempotent(aws):
    put_clean_batch(aws)
    build_manifest()
    run_copy()
    first = landing_keys(aws)
    run_copy()
    assert landing_keys(aws) == first


def test_throttling_raises_transient_error(aws, monkeypatch):
    put_clean_batch(aws)
    build_manifest()

    class Throttled:
        def copy_object(self, **kw):
            raise ClientError({"Error": {"Code": "SlowDown", "Message": "x"}}, "CopyObject")

    entry = {"source_key": "a", "dest_key": "b", "action": "copy", "size": 1}
    with pytest.raises(c.TransientS3Error):
        copy_files.copy_one(Throttled(), c.settings(), entry)


def test_access_denied_is_a_result_not_a_crash(aws):
    class Denied:
        def copy_object(self, **kw):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "CopyObject")

    entry = {"source_key": "a", "dest_key": "b", "action": "copy", "size": 1}
    assert copy_files.copy_one(Denied(), c.settings(), entry)[0] == "denied"


def test_object_over_5gib_is_flagged_not_attempted(aws):
    entry = {"source_key": "a", "dest_key": "b", "action": "copy", "size": c.MAX_SINGLE_COPY_BYTES + 1}
    assert copy_files.copy_one(object(), c.settings(), entry) == ("failed", "ObjectTooLargeForSingleCopy")
