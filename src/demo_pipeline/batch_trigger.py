"""Account B: batch trigger. Invoked by hand, once per batch.

Lists the loan folders of a batch in the landing zone (which lives in Account A) and
sends one message per loan to a FIFO queue. Each loan is its own message group.
"""
import json
import os

import boto3

from . import common as c


def handler(event, _context=None):
    bucket = os.environ["LANDING_BUCKET"]
    landing_prefix = os.environ.get("LANDING_PREFIX", "Acquisition/")
    queue_url = os.environ["QUEUE_URL"]
    acquisition = c.validate_acquisition(event["acquisition"])
    batch = c.validate_name(event["batch"], "batch")

    s3 = boto3.client("s3")
    sqs = boto3.client("sqs")
    prefix = f"{landing_prefix}{acquisition}/{batch}/"

    loans = []
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix, Delimiter="/"
    ):
        for cp in page.get("CommonPrefixes", []):
            loans.append(cp["Prefix"][len(prefix):].rstrip("/"))

    sent = 0
    for group in c.chunked(loans, 10):  # SQS batch limit is 10
        entries = [
            {
                "Id": str(i),
                "MessageBody": json.dumps({"acquisition": acquisition, "batch": batch, "loan": loan}),
                "MessageGroupId": loan,                              # one group per loan
                "MessageDeduplicationId": f"{acquisition}-{batch}-{loan}",
            }
            for i, loan in enumerate(group)
        ]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        if resp.get("Failed"):
            raise RuntimeError(f"SQS rejected messages: {resp['Failed']}")
        sent += len(entries)
    return {"acquisition": acquisition, "batch": batch, "loans_queued": sent}
