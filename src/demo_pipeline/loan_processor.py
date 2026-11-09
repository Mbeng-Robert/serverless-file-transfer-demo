"""Account B: loan processing. Triggered by the FIFO queue with batch size 1.

For one loan: map the partner's loan number and document type numbers through
DynamoDB, move unmapped documents to UNPROCESSED/, and write one trigger file under
TRIGGERS/<batch>/ for the downstream loader. A failure raises, so SQS redelivers
and, after maxReceiveCount, moves the message to the dead-letter queue.
"""
import json
import os
from datetime import datetime, timezone

import boto3

from . import common as c


def _env():
    return {
        "bucket": os.environ["LANDING_BUCKET"],
        "prefix": os.environ.get("LANDING_PREFIX", "Acquisition/"),
        "loan_table": os.environ["LOAN_TABLE"],
        "doc_table": os.environ["DOCTYPE_TABLE"],
    }


def process_loan(s3, ddb, env, acquisition, batch, loan):
    loan_prefix = f"{env['prefix']}{acquisition}/{batch}/{loan}/"
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=env["bucket"], Prefix=loan_prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []) if not c.is_folder_marker(o["Key"]))

    loan_row = ddb.get_item(
        TableName=env["loan_table"], Key={"source_loan_number": {"S": loan}}
    ).get("Item")
    target_loan = loan_row["target_loan_id"]["S"] if loan_row else None

    mapped, unprocessed = [], []
    doc_cache = {}
    for key in sorted(keys):
        name = key.rsplit("/", 1)[-1]
        parsed = c.parse_filename(name)
        target_doc = None
        if target_loan and parsed:
            src_type = parsed["doc_type"]
            if src_type not in doc_cache:
                row = ddb.get_item(
                    TableName=env["doc_table"], Key={"source_doc_type": {"S": src_type}}
                ).get("Item")
                doc_cache[src_type] = row["target_doc_type"]["S"] if row else None
            target_doc = doc_cache[src_type]
        if target_doc:
            mapped.append({"file": name, "key": key, "source_doc_type": parsed["doc_type"],
                           "target_doc_type": target_doc})
        else:
            unprocessed.append(key)

    for key in unprocessed:
        name = key.rsplit("/", 1)[-1]
        s3.copy_object(
            Bucket=env["bucket"],
            Key=f"{env['prefix']}UNPROCESSED/{acquisition}/{batch}/{loan}/{name}",
            CopySource={"Bucket": env["bucket"], "Key": key},
            TaggingDirective="REPLACE",
        )

    trigger_key = None
    if target_loan and mapped:
        trigger_key = f"{env['prefix']}TRIGGERS/{batch}/{loan}.json"
        c.write_json(s3, env["bucket"], trigger_key, {
            "acquisition": acquisition, "batch": batch,
            "source_loan_number": loan, "target_loan_id": target_loan,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "documents": mapped,
        })
    return {"loan": loan, "mapped": len(mapped), "unprocessed": len(unprocessed),
            "trigger": trigger_key}


def handler(event, _context=None):
    env = _env()
    s3, ddb = boto3.client("s3"), boto3.client("dynamodb")
    results = []
    for record in event["Records"]:
        body = json.loads(record["body"])
        results.append(process_loan(
            s3, ddb, env,
            c.validate_acquisition(body["acquisition"]),
            c.validate_name(body["batch"], "batch"),
            c.validate_name(body["loan"], "loan"),
        ))
    return results
