provider "aws" {
  region = var.region

  default_tags {
    tags = var.tags
  }
}

provider "aws" {
  alias   = "account_b"
  region  = var.region
  profile = var.account_b_profile

  default_tags {
    tags = var.tags
  }
}

data "aws_caller_identity" "account_a" {}

locals {
  account_a_id        = data.aws_caller_identity.account_a.account_id
  intake_bucket_name  = "${var.project_name}-a-intake-${local.account_a_id}"
  landing_bucket_name = "${var.project_name}-a-landing-${local.account_a_id}"
  src_dir             = "${path.root}/../src"
  build_dir           = "${path.root}/build"
}

# Account B comes first: Account A's landing-zone bucket policy needs the ARNs of
# Account B's roles. Account B only needs the landing bucket NAME, which is
# computed above, so there is no dependency cycle.
module "account_b" {
  source = "./modules/account_b"

  providers = {
    aws = aws.account_b
  }

  name_prefix         = "${var.project_name}-b"
  landing_bucket_name = local.landing_bucket_name
  account_a_id        = local.account_a_id
  src_dir             = local.src_dir
  build_dir           = local.build_dir
  lambda_memory_mb    = var.lambda_memory_mb
  log_retention_days  = var.log_retention_days
}

module "account_a" {
  source = "./modules/account_a"

  name_prefix              = "${var.project_name}-a"
  intake_bucket_name       = local.intake_bucket_name
  landing_bucket_name      = local.landing_bucket_name
  account_b_role_arns      = module.account_b.lambda_role_arns
  src_dir                  = local.src_dir
  build_dir                = local.build_dir
  openpyxl_layer_zip       = var.openpyxl_layer_zip
  chunk_size               = var.chunk_size
  manifest_map_concurrency = var.manifest_map_concurrency
  copy_map_concurrency     = var.copy_map_concurrency
  copy_threads             = var.copy_threads
  sfn_timeout_seconds      = var.sfn_timeout_seconds
  lambda_memory_mb         = var.lambda_memory_mb
  log_retention_days       = var.log_retention_days
  work_retention_days      = var.work_retention_days
}
