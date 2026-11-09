variable "name_prefix" { type = string }
variable "intake_bucket_name" { type = string }
variable "landing_bucket_name" { type = string }

variable "account_b_role_arns" {
  description = "Account B Lambda roles that may read and write the landing zone."
  type        = list(string)
}

variable "src_dir" { type = string }
variable "build_dir" { type = string }
variable "openpyxl_layer_zip" { type = string }
variable "chunk_size" { type = number }
variable "manifest_map_concurrency" { type = number }
variable "copy_map_concurrency" { type = number }
variable "copy_threads" { type = number }
variable "sfn_timeout_seconds" { type = number }
variable "lambda_memory_mb" { type = number }
variable "log_retention_days" { type = number }
variable "work_retention_days" { type = number }
