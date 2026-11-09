"""Whole flow with fake AWS: Account A pipelines, then Account B trigger files."""
import json

import boto3

from conftest import ACQ, BATCH, COPY_RUN, LANDING, RUN, intake_key, make_ddb, put, put_clean_batch, seed_mappings
from demo_pipeline import batch_trigger, copy_chunker, copy_files, loan_processor, merge_manifest, scan_batch, validate_chunk


def test_intake_to_trigger_files(aws, monkeypatch):
    # Intake: two loans with 3 good files each, one unknown doc type, one bad file.
    put_clean_batch(aws)
    put(aws, intake_key("1001", "1001_ZZZZ_20240115_009.pdf"))
    put(aws, intake_key("1002", "wrong-name.pdf"))

    ev = {"acquisition": ACQ, "batch": BATCH, "run_id": RUN}
    scan = scan_batch.handler(ev)
    for chunk in scan["chunks"]:
        validate_chunk.handler({**ev, "chunk_key": chunk})
    manifest = merge_manifest.handler(ev)
    assert manifest["valid"] == 7 and manifest["failed"] == 1

    cev = {"acquisition": ACQ, "batch": BATCH, "run_id": COPY_RUN, "manifest_run_id": RUN}
    for chunk in copy_chunker.handler(cev)["chunks"]:
        copy_files.handler({**cev, "chunk_key": chunk})
    assert copy_chunker.summary_handler(cev)["clean"] is True

    # Account B
    sqs = boto3.client("sqs", region_name="us-east-1")
    url = sqs.create_queue(QueueName="q.fifo", Attributes={"FifoQueue": "true"})["QueueUrl"]
    monkeypatch.setenv("QUEUE_URL", url)
    seed_mappings(make_ddb(), {"1001": "T-1", "1002": "T-2"}, {"NOTE": "10", "DEED": "20", "APPR": "30"})
    assert batch_trigger.handler({"acquisition": ACQ, "batch": BATCH})["loans_queued"] == 2

    while True:
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1).get("Messages", [])
        if not msgs:
            break
        loan_processor.handler({"Records": [{"body": msgs[0]["Body"]}]})
        sqs.delete_message(QueueUrl=url, ReceiptHandle=msgs[0]["ReceiptHandle"])

    keys = [o["Key"] for o in aws.list_objects_v2(Bucket=LANDING, Prefix="Acquisition/")["Contents"]]
    assert "Acquisition/TRIGGERS/BATCH001/1001.json" in keys
    assert "Acquisition/TRIGGERS/BATCH001/1002.json" in keys
    assert "Acquisition/UNPROCESSED/ACQ01/BATCH001/1001/1001_ZZZZ_20240115_009.pdf" in keys
    assert "Acquisition/ERRORS/ACQ01/BATCH001/1002/wrong-name.pdf" in keys
    t = json.loads(aws.get_object(Bucket=LANDING, Key="Acquisition/TRIGGERS/BATCH001/1001.json")["Body"].read())
    assert len(t["documents"]) == 3
