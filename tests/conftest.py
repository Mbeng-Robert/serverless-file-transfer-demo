import boto3
import pytest
from moto import mock_aws

INTAKE = "demo-intake"
LANDING = "demo-landing"
LOAN_TABLE = "demo-loan-mapping"
DOC_TABLE = "demo-doctype-mapping"
ACQ = "ACQ01"
BATCH = "BATCH001"
RUN = "run-1"
COPY_RUN = "copy-run-1"
SCAN_OK = "NO_MALWARE_FOUND"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    values = {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "INTAKE_BUCKET": INTAKE,
        "LANDING_BUCKET": LANDING,
        "CHUNK_SIZE": "4",
        "COPY_THREADS": "4",
        "LOAN_TABLE": LOAN_TABLE,
        "DOCTYPE_TABLE": DOC_TABLE,
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def aws():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=INTAKE)
        s3.create_bucket(Bucket=LANDING)
        yield s3


def put(s3, key, body=b"x", status=SCAN_OK):
    s3.put_object(Bucket=INTAKE, Key=key, Body=body)
    if status:
        s3.put_object_tagging(
            Bucket=INTAKE, Key=key,
            Tagging={"TagSet": [{"Key": "GuardDutyMalwareScanStatus", "Value": status}]},
        )


def intake_key(loan, name, batch=BATCH, acq=ACQ):
    return f"partner-sftp/{acq}/{batch}/{loan}/{name}"


def put_folder_markers(s3, loans, batch=BATCH, acq=ACQ):
    s3.put_object(Bucket=INTAKE, Key=f"partner-sftp/{acq}/{batch}/", Body=b"")
    for loan in loans:
        s3.put_object(Bucket=INTAKE, Key=f"partner-sftp/{acq}/{batch}/{loan}/", Body=b"")


def put_clean_batch(s3):
    """Two loans, three good files each, plus SFTP folder markers."""
    loans = ["1001", "1002"]
    put_folder_markers(s3, loans)
    for loan in loans:
        for n, doc in enumerate(["NOTE", "DEED", "APPR"], start=1):
            put(s3, intake_key(loan, f"{loan}_{doc}_20240115_{n:03d}.pdf"))
    return 6


def make_ddb():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    for table, key in ((LOAN_TABLE, "source_loan_number"), (DOC_TABLE, "source_doc_type")):
        ddb.create_table(
            TableName=table,
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
    return ddb


def seed_mappings(ddb, loans, doc_types):
    for src, tgt in loans.items():
        ddb.put_item(TableName=LOAN_TABLE, Item={"source_loan_number": {"S": src}, "target_loan_id": {"S": tgt}})
    for src, tgt in doc_types.items():
        ddb.put_item(TableName=DOC_TABLE, Item={"source_doc_type": {"S": src}, "target_doc_type": {"S": tgt}})
