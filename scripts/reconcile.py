#!/usr/bin/env python3
"""After both pipelines ran, prove nothing was lost. Read-only.

  intake real files  ==  manifest valid + failed
  landing copies     ==  manifest valid          (Acquisition/<acq>/<batch>/)
  ERRORS copies      ==  manifest failed         (Acquisition/ERRORS/<acq>/<batch>/)
Then reports how many trigger files exist for the batch (Account B's output).
"""
import argparse
import json
import sys

import boto3


def count(s3, bucket, prefix, skip_markers=True):
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        n += sum(1 for o in page.get("Contents", []) if not (skip_markers and o["Key"].endswith("/")))
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--intake-bucket", required=True)
    p.add_argument("--landing-bucket", required=True)
    p.add_argument("--acquisition", required=True)
    p.add_argument("--batch", required=True)
    p.add_argument("--manifest-run-id", required=True, help="execution name of the manifest run")
    a = p.parse_args()

    s3 = boto3.client("s3")
    summary = json.loads(s3.get_object(
        Bucket=a.landing_bucket,
        Key=f"Acquisition/MANIFEST/{a.acquisition}/{a.batch}/{a.manifest_run_id}/summary.json",
    )["Body"].read())

    intake = count(s3, a.intake_bucket, f"partner-sftp/{a.acquisition}/{a.batch}/")
    landed = count(s3, a.landing_bucket, f"Acquisition/{a.acquisition}/{a.batch}/")
    errors = count(s3, a.landing_bucket, f"Acquisition/ERRORS/{a.acquisition}/{a.batch}/")
    triggers = count(s3, a.landing_bucket, f"Acquisition/TRIGGERS/{a.batch}/")

    checks = {
        "intake files == valid + failed": intake == summary["valid"] + summary["failed"],
        "landing copies == valid": landed == summary["valid"],
        "ERRORS copies == failed": errors == summary["failed"],
    }
    print(f"intake={intake} valid={summary['valid']} failed={summary['failed']} "
          f"landed={landed} errors={errors} trigger_files={triggers}")
    for name, ok in checks.items():
        print(("PASS  " if ok else "FAIL  ") + name)
    print("PASS" if all(checks.values()) else "FAIL")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
