# Account B: mapping tables, the FIFO loan queue with its dead-letter queue, and the
# two Lambda functions (batch trigger, loan processing).

locals {
  landing_arn = "arn:aws:s3:::${var.landing_bucket_name}"
}

# --- DynamoDB mapping tables (on demand, point-in-time recovery) -----------------

resource "aws_dynamodb_table" "loan_mapping" {
  name         = "${var.name_prefix}-loan-mapping"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "source_loan_number"

  attribute {
    name = "source_loan_number"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "doctype_mapping" {
  name         = "${var.name_prefix}-doctype-mapping"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "source_doc_type"

  attribute {
    name = "source_doc_type"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# --- SQS: FIFO queue, one message group per loan, dead-letter after 3 receives ---

resource "aws_sqs_queue" "dead_letter" {
  name                      = "${var.name_prefix}-loan-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "loan" {
  name                       = "${var.name_prefix}-loan-queue.fifo"
  fifo_queue                 = true
  visibility_timeout_seconds = 1000 # must be longer than the loan Lambda timeout

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 3
  })
}

# --- Lambda ------------------------------------------------------------------------

data "archive_file" "code" {
  type        = "zip"
  source_dir  = var.src_dir
  output_path = "${var.build_dir}/account-b-code.zip"
  excludes    = ["__pycache__", "demo_pipeline/__pycache__"]
}

locals {
  functions = {
    batch_trigger = { handler = "demo_pipeline.batch_trigger.handler", timeout = 300 }
    loan          = { handler = "demo_pipeline.loan_processor.handler", timeout = 300 }
  }
}

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
  logs_statement = {
    Effect   = "Allow"
    Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    Resource = ["arn:aws:logs:*:*:log-group:/aws/lambda/${var.name_prefix}-*:*"]
  }

  policies = {
    batch_trigger = [
      {
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = [local.landing_arn]
        Condition = { StringLike = { "s3:prefix" = ["Acquisition/*"] } }
      },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = [aws_sqs_queue.loan.arn] },
    ]
    loan = [
      {
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = [local.landing_arn]
        Condition = { StringLike = { "s3:prefix" = ["Acquisition/*"] } }
      },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["${local.landing_arn}/Acquisition/*"] },
      {
        Effect = "Allow"
        Action = ["s3:PutObject"]
        Resource = [
          "${local.landing_arn}/Acquisition/TRIGGERS/*",
          "${local.landing_arn}/Acquisition/UNPROCESSED/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem"]
        Resource = [aws_dynamodb_table.loan_mapping.arn, aws_dynamodb_table.doctype_mapping.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = [aws_sqs_queue.loan.arn]
      },
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

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.functions
  name              = "/aws/lambda/${var.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${var.name_prefix}-${each.key}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  handler          = each.value.handler
  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256
  timeout          = each.value.timeout
  memory_size      = var.lambda_memory_mb

  environment {
    variables = {
      LANDING_BUCKET = var.landing_bucket_name
      QUEUE_URL      = aws_sqs_queue.loan.url
      LOAN_TABLE     = aws_dynamodb_table.loan_mapping.name
      DOCTYPE_TABLE  = aws_dynamodb_table.doctype_mapping.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}

# The queue invokes the loan Lambda one message at a time.
resource "aws_lambda_event_source_mapping" "loan" {
  event_source_arn = aws_sqs_queue.loan.arn
  function_name    = aws_lambda_function.fn["loan"].arn
  batch_size       = 1
}
