# One role per Lambda, each limited to the prefixes it actually uses.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each           = local.functions
  name               = "${var.name_prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

locals {
  intake_arn  = aws_s3_bucket.intake.arn
  landing_arn = aws_s3_bucket.landing.arn

  logs_statement = {
    Effect   = "Allow"
    Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    Resource = ["arn:aws:logs:*:*:log-group:/aws/lambda/${var.name_prefix}-*:*"]
  }

  policies = {
    scan = [
      # ListBucket is also what makes S3 answer 404 instead of 403 for a missing key.
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [local.intake_arn] },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${local.landing_arn}/work/*"] },
    ]
    validate = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [local.intake_arn] },
      { Effect = "Allow", Action = ["s3:GetObjectTagging"], Resource = ["${local.intake_arn}/*"] },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = ["${local.landing_arn}/work/*"] },
    ]
    merge = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [local.landing_arn] },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.landing_arn}/work/*"] },
      {
        Effect = "Allow"
        Action = ["s3:PutObject"]
        Resource = [
          "${local.landing_arn}/Acquisition/MANIFEST/*",
          "${local.landing_arn}/copy-manifests/*",
        ]
      },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${local.intake_arn}/quarantine-reports/*"] },
    ]
    chunker = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.landing_arn}/copy-manifests/*"] },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${local.landing_arn}/work/*"] },
    ]
    copy = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [local.intake_arn] },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.intake_arn}/partner-sftp/*"] },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.landing_arn}/work/*"] },
      {
        Effect = "Allow"
        Action = ["s3:PutObject"]
        Resource = [
          "${local.landing_arn}/Acquisition/*",
          "${local.landing_arn}/work/*",
        ]
      },
    ]
    summary = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = [local.landing_arn] },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.landing_arn}/work/*"] },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = ["${local.landing_arn}/copy-manifests/*"] },
    ]
  }
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  name     = "access"
  role     = aws_iam_role.lambda[each.key].id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = concat([local.logs_statement], local.policies[each.key])
  })
}
