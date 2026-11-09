data "archive_file" "code" {
  type        = "zip"
  source_dir  = var.src_dir
  output_path = "${var.build_dir}/account-a-code.zip"
  excludes    = ["__pycache__", "demo_pipeline/__pycache__"]
}

resource "aws_lambda_layer_version" "openpyxl" {
  layer_name          = "${var.name_prefix}-openpyxl"
  filename            = var.openpyxl_layer_zip
  source_code_hash    = filebase64sha256(var.openpyxl_layer_zip)
  compatible_runtimes = ["python3.12"]
}

locals {
  functions = {
    scan = {
      handler = "demo_pipeline.scan_batch.handler"
      timeout = 900
      memory  = var.lambda_memory_mb
      layers  = []
    }
    validate = {
      handler = "demo_pipeline.validate_chunk.handler"
      timeout = 300
      memory  = var.lambda_memory_mb
      layers  = []
    }
    merge = {
      handler = "demo_pipeline.merge_manifest.handler"
      timeout = 900
      memory  = var.lambda_memory_mb
      layers  = [aws_lambda_layer_version.openpyxl.arn]
    }
    chunker = {
      handler = "demo_pipeline.copy_chunker.handler"
      timeout = 300
      memory  = 512
      layers  = []
    }
    copy = {
      handler = "demo_pipeline.copy_files.handler"
      timeout = 900
      memory  = var.lambda_memory_mb
      layers  = []
    }
    summary = {
      handler = "demo_pipeline.copy_chunker.summary_handler"
      timeout = 300
      memory  = 512
      layers  = []
    }
  }
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
  memory_size      = each.value.memory
  layers           = each.value.layers

  environment {
    variables = {
      INTAKE_BUCKET  = aws_s3_bucket.intake.bucket
      LANDING_BUCKET = aws_s3_bucket.landing.bucket
      CHUNK_SIZE     = tostring(var.chunk_size)
      COPY_THREADS   = tostring(var.copy_threads)
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}
