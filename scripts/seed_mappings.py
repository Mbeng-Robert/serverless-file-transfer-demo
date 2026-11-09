#!/usr/bin/env python3
"""Fill Account B's mapping tables with made-up data.

Loans 100000.. are mapped except every 5th one (to show UNPROCESSED/ handling), and
document type TITL is deliberately left unmapped.
"""
import argparse

import boto3


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--loan-table", required=True)
    p.add_argument("--doctype-table", required=True)
    p.add_argument("--loans", type=int, default=10)
    p.add_argument("--profile", help="AWS profile for Account B (omit if same account)")
    a = p.parse_args()

    ddb = boto3.Session(profile_name=a.profile).client("dynamodb")
    for i in range(a.loans):
        if i % 5 == 4:
            continue
        ddb.put_item(TableName=a.loan_table, Item={
            "source_loan_number": {"S": str(100000 + i)},
            "target_loan_id": {"S": f"T-{500000 + i}"},
        })
    for src, tgt in {"NOTE": "10", "DEED": "20", "APPR": "30"}.items():
        ddb.put_item(TableName=a.doctype_table, Item={
            "source_doc_type": {"S": src}, "target_doc_type": {"S": tgt}})
    print("Seeded mapping tables")


if __name__ == "__main__":
    main()
