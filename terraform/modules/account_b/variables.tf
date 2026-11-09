variable "name_prefix" { type = string }

variable "landing_bucket_name" {
  description = "Landing-zone bucket owned by Account A."
  type        = string
}

variable "account_a_id" { type = string }
variable "src_dir" { type = string }
variable "build_dir" { type = string }
variable "lambda_memory_mb" { type = number }
variable "log_retention_days" { type = number }
