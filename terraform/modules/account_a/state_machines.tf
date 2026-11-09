resource "aws_cloudwatch_log_group" "sfn" {
  for_each          = toset(["manifest", "copy"])
  name              = "/aws/vendedlogs/states/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  for_each           = toset(["manifest", "copy"])
  name               = "${var.name_prefix}-sfn-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

locals {
  sfn_functions = {
    manifest = [aws_lambda_function.fn["scan"].arn, aws_lambda_function.fn["validate"].arn, aws_lambda_function.fn["merge"].arn]
    copy     = [aws_lambda_function.fn["chunker"].arn, aws_lambda_function.fn["copy"].arn, aws_lambda_function.fn["summary"].arn]
  }
}

resource "aws_iam_role_policy" "sfn" {
  for_each = local.sfn_functions
  name     = "invoke-and-log"
  role     = aws_iam_role.sfn[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = concat(each.value, [for arn in each.value : "${arn}:*"])
      },
      {
        # Log delivery actions do not support resource-level permissions.
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
        ]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_sfn_state_machine" "manifest" {
  name     = "${var.name_prefix}-manifest-pipeline"
  role_arn = aws_iam_role.sfn["manifest"].arn

  definition = templatefile("${path.module}/../../../statemachine/manifest_pipeline.asl.json.tftpl", {
    timeout_seconds = var.sfn_timeout_seconds
    map_concurrency = var.manifest_map_concurrency
    scan_arn        = aws_lambda_function.fn["scan"].arn
    validate_arn    = aws_lambda_function.fn["validate"].arn
    merge_arn       = aws_lambda_function.fn["merge"].arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn["manifest"].arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  depends_on = [aws_iam_role_policy.sfn]
}

resource "aws_sfn_state_machine" "copy" {
  name     = "${var.name_prefix}-copy-pipeline"
  role_arn = aws_iam_role.sfn["copy"].arn

  definition = templatefile("${path.module}/../../../statemachine/copy_pipeline.asl.json.tftpl", {
    timeout_seconds = var.sfn_timeout_seconds
    map_concurrency = var.copy_map_concurrency
    chunker_arn     = aws_lambda_function.fn["chunker"].arn
    copy_arn        = aws_lambda_function.fn["copy"].arn
    summary_arn     = aws_lambda_function.fn["summary"].arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn["copy"].arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  depends_on = [aws_iam_role_policy.sfn]
}
