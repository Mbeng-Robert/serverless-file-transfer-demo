#!/usr/bin/env python3
"""Create a made-up partner upload in the intake bucket (what SFTP would leave behind).

Includes a few deliberately bad files so the validation rules have something to catch.
Real malware-scan tags come from the scanner; here every good file is tagged clean.
"""
import argparse

import boto3

DOC_TYPES = ["NOTE", "DEED", "APPR", "TITL"]


def tag(s3, bucket, key, status):
    s3.put_object_tagging(
        Bucket=bucket, Key=key,
        Tagging={"TagSet": [{"Key": "GuardDutyMalwareScanStatus", "Value": status}]},
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", required=True, help="intake bucket")
    p.add_argument("--acquisition", default="ACQ01")
    p.add_argument("--batch", default="BATCH001")
    p.add_argument("--loans", type=int, default=10)
    p.add_argument("--files-per-loan", type=int, default=4)
    p.add_argument("--no-bad-files", action="store_true")
    a = p.parse_args()

    s3 = boto3.client("s3")
    root = f"partner-sftp/{a.acquisition}/{a.batch}/"
    s3.put_object(Bucket=a.bucket, Key=root, Body=b"")
    first_loan = None
    for i in range(a.loans):
        loan = str(100000 + i)
        first_loan = first_loan or loan
        s3.put_object(Bucket=a.bucket, Key=f"{root}{loan}/", Body=b"")
        for n in range(a.files_per_loan):
            doc = DOC_TYPES[n % len(DOC_TYPES)]
            key = f"{root}{loan}/{loan}_{doc}_20240115_{n + 1:03d}.pdf"
            s3.put_object(Bucket=a.bucket, Key=key, Body=b"%PDF-1.4 sample")
            tag(s3, a.bucket, key, "NO_MALWARE_FOUND")

    if not a.no_bad_files and first_loan:
        bad = {
            f"{first_loan}_NOTE_20240115_900.docx": "NO_MALWARE_FOUND",      # extension
            "scan-final.pdf": "NO_MALWARE_FOUND",                             # file name
            "999999_NOTE_20240115_901.pdf": "NO_MALWARE_FOUND",              # wrong loan folder
            f"{first_loan}_DEED_20240115_902.pdf": "THREATS_FOUND",          # malware tag
        }
        for name, status in bad.items():
            key = f"{root}{first_loan}/{name}"
            s3.put_object(Bucket=a.bucket, Key=key, Body=b"sample")
            tag(s3, a.bucket, key, status)
        dup = f"{root}{first_loan}/{first_loan}_NOTE_20240115_001.tif"        # duplicate id
        s3.put_object(Bucket=a.bucket, Key=dup, Body=b"sample")
        tag(s3, a.bucket, dup, "NO_MALWARE_FOUND")
    print(f"Created s3://{a.bucket}/{root}")


if __name__ == "__main__":
    main()
