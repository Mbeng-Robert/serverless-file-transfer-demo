# Account A: the intake bucket (the partner's SFTP uploads land here) and the
# landing zone (validated files, manifests, trigger files).

resource "aws_s3_bucket" "intake" {
  bucket = var.intake_bucket_name
}

resource "aws_s3_bucket" "landing" {
  bucket = var.landing_bucket_name
}

resource "aws_s3_bucket_public_access_block" "intake" {
  bucket                  = aws_s3_bucket.intake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "landing" {
  bucket                  = aws_s3_bucket.landing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3 keeps the demo simple. With a customer-managed KMS key, every role that
# reads or writes these buckets (including Account B's) also needs kms:Decrypt /
# kms:GenerateDataKey, and the key policy or a grant must allow Account B.
resource "aws_s3_bucket_server_side_encryption_configuration" "intake" {
  bucket = aws_s3_bucket.intake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Chunk and result files under work/ are temporary.
resource "aws_s3_bucket_lifecycle_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id

  rule {
    id     = "expire-work-files"
    status = "Enabled"

    filter {
      prefix = "work/"
    }

    expiration {
      days = var.work_retention_days
    }
  }

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "intake" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.intake.arn, "${aws_s3_bucket.intake.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

data "aws_iam_policy_document" "landing" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.landing.arn, "${aws_s3_bucket.landing.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Cross-account access: Account B's two Lambda roles can list the landing zone,
  # read documents, and write trigger files and UNPROCESSED copies. Nothing else.
  statement {
    sid       = "AccountBList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.landing.arn]

    principals {
      type        = "AWS"
      identifiers = var.account_b_role_arns
    }

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["Acquisition/*"]
    }
  }

  statement {
    sid       = "AccountBRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.landing.arn}/Acquisition/*"]

    principals {
      type        = "AWS"
      identifiers = var.account_b_role_arns
    }
  }

  statement {
    sid     = "AccountBWrite"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.landing.arn}/Acquisition/TRIGGERS/*",
      "${aws_s3_bucket.landing.arn}/Acquisition/UNPROCESSED/*",
    ]

    principals {
      type        = "AWS"
      identifiers = var.account_b_role_arns
    }
  }
}

resource "aws_s3_bucket_policy" "intake" {
  bucket = aws_s3_bucket.intake.id
  policy = data.aws_iam_policy_document.intake.json

  depends_on = [aws_s3_bucket_public_access_block.intake]
}

resource "aws_s3_bucket_policy" "landing" {
  bucket = aws_s3_bucket.landing.id
  policy = data.aws_iam_policy_document.landing.json

  depends_on = [aws_s3_bucket_public_access_block.landing]
}
