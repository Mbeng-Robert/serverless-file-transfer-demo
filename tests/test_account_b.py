import json

import boto3
import pytest

from conftest import ACQ, BATCH, LANDING, make_ddb, seed_mappings
from demo_pipeline import batch_trigger, loan_processor


def put_landing(aws, loan, names):
    for n in names:
        aws.put_object(Bucket=LANDING, Key=f"Acquisition/{ACQ}/{BATCH}/{loan}/{n}", Body=b"x")


@pytest.fixture
def b_side(aws, monkeypatch):
    sqs = boto3.client("sqs", region_name="us-east-1")
    url = sqs.create_queue(
        QueueName="loan-queue.fifo",
        Attributes={"FifoQueue": "true", "VisibilityTimeout": "1000"},
    )["QueueUrl"]
    monkeypatch.setenv("QUEUE_URL", url)
    ddb = make_ddb()
    seed_mappings(ddb, {"1001": "T-9001", "1002": "T-9002"}, {"NOTE": "10", "DEED": "20"})
    return sqs, url


def test_batch_trigger_sends_one_message_per_loan(aws, b_side):
    sqs, url = b_side
    put_landing(aws, "1001", ["1001_NOTE_20240115_001.pdf", "1001_DEED_20240115_002.pdf"])
    put_landing(aws, "1002", ["1002_NOTE_20240115_001.pdf"])
    # not loans of this batch: must not be queued
    aws.put_object(Bucket=LANDING, Key=f"Acquisition/ERRORS/{ACQ}/{BATCH}/1003/x.txt", Body=b"x")
    out = batch_trigger.handler({"acquisition": ACQ, "batch": BATCH})
    assert out["loans_queued"] == 2
    got = []
    for _ in range(5):
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
        got += msgs
        for m in msgs:
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    assert sorted(json.loads(m["Body"])["loan"] for m in got) == ["1001", "1002"]


def test_queue_is_empty_when_batch_has_no_loans(aws, b_side):
    assert batch_trigger.handler({"acquisition": ACQ, "batch": BATCH})["loans_queued"] == 0


def run_loan(loan):
    body = json.dumps({"acquisition": ACQ, "batch": BATCH, "loan": loan})
    return loan_processor.handler({"Records": [{"body": body}]})[0]


def test_mapped_loan_gets_trigger_file(aws, b_side):
    put_landing(aws, "1001", ["1001_NOTE_20240115_001.pdf", "1001_DEED_20240115_002.pdf"])
    out = run_loan("1001")
    assert out["mapped"] == 2 and out["unprocessed"] == 0
    trigger = json.loads(aws.get_object(Bucket=LANDING, Key=out["trigger"])["Body"].read())
    assert out["trigger"] == "Acquisition/TRIGGERS/BATCH001/1001.json"
    assert trigger["target_loan_id"] == "T-9001"
    assert {d["target_doc_type"] for d in trigger["documents"]} == {"10", "20"}


def test_unmapped_document_type_goes_to_unprocessed(aws, b_side):
    put_landing(aws, "1001", ["1001_NOTE_20240115_001.pdf", "1001_ZZZZ_20240115_002.pdf"])
    out = run_loan("1001")
    assert out["mapped"] == 1 and out["unprocessed"] == 1
    key = f"Acquisition/UNPROCESSED/{ACQ}/{BATCH}/1001/1001_ZZZZ_20240115_002.pdf"
    aws.head_object(Bucket=LANDING, Key=key)
    trigger = json.loads(aws.get_object(Bucket=LANDING, Key=out["trigger"])["Body"].read())
    assert [d["file"] for d in trigger["documents"]] == ["1001_NOTE_20240115_001.pdf"]


def test_unmapped_loan_sends_everything_to_unprocessed_and_no_trigger(aws, b_side):
    put_landing(aws, "7777", ["7777_NOTE_20240115_001.pdf"])
    out = run_loan("7777")
    assert out["trigger"] is None and out["unprocessed"] == 1
    listing = aws.list_objects_v2(Bucket=LANDING, Prefix="Acquisition/TRIGGERS/")
    assert listing["KeyCount"] == 0


def test_rerun_overwrites_trigger_file_not_duplicates(aws, b_side):
    put_landing(aws, "1001", ["1001_NOTE_20240115_001.pdf"])
    run_loan("1001")
    run_loan("1001")
    assert aws.list_objects_v2(Bucket=LANDING, Prefix="Acquisition/TRIGGERS/")["KeyCount"] == 1


def test_loan_name_cannot_escape_the_prefix(aws, b_side):
    body = json.dumps({"acquisition": ACQ, "batch": BATCH, "loan": "../ERRORS"})
    with pytest.raises(ValueError):
        loan_processor.handler({"Records": [{"body": body}]})
