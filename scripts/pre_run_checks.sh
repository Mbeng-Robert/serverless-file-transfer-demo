#!/usr/bin/env bash
# Count a batch in the intake bucket WITHOUT changing anything.
#   all objects = folder markers + zero-byte real files + non-zero files
#   real files  = all objects - folder markers
# Usage: INTAKE_BUCKET=... ./pre_run_checks.sh ACQ01 BATCH001
set -euo pipefail
: "${INTAKE_BUCKET:?set INTAKE_BUCKET}"
ACQ="${1:?acquisition}"; BATCH="${2:?batch}"
PREFIX="partner-sftp/${ACQ}/${BATCH}/"

aws s3api list-objects-v2 --bucket "$INTAKE_BUCKET" --prefix "$PREFIX" \
    --query 'Contents[].[Key,Size]' --output text > /tmp/batch_listing.txt || true

total=$(wc -l < /tmp/batch_listing.txt)
markers=$(awk -F'\t' '$1 ~ /\/$/' /tmp/batch_listing.txt | wc -l)   # keys ending in "/"
zero=$(awk -F'\t' '$1 !~ /\/$/ && $2 == 0' /tmp/batch_listing.txt | wc -l)
real=$((total - markers))
nonzero=$((real - zero))
loans=$(awk -F'\t' '$1 ~ /\/$/' /tmp/batch_listing.txt | awk -F/ 'NF==5' | wc -l)

echo "prefix:            s3://${INTAKE_BUCKET}/${PREFIX}"
echo "all objects:       $total"
echo "folder markers:    $markers  (loan folders: $loans, batch marker: $((markers - loans)))"
echo "zero-byte files:   $zero"
echo "non-zero files:    $nonzero"
echo "real files:        $real"

if [ "$((markers + zero + nonzero))" -eq "$total" ]; then echo "CHECK OK"; else echo "CHECK FAILED"; exit 1; fi
