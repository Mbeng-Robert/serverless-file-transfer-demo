variable "project_name" {
  description = "Prefix for resource names."
  type        = string
  default     = "file-transfer-demo"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "account_b_profile" {
  description = <<-EOT
    AWS CLI profile for Account B. Leave null to create Account B's resources in the
    same AWS account as Account A: the demo then simulates two accounts with separate
    roles and a bucket policy, which is enough to see cross-account permissions work.
    Set it to a profile for a real second account to deploy Account B there.
  EOT
  type        = string
  default     = null
}

variable "chunk_size" {
  description = "Files per chunk (one Lambda invocation handles one chunk)."
  type        = number
  default     = 1000
}

variable "manifest_map_concurrency" {
  description = "Chunks validated at the same time by the manifest pipeline."
  type        = number
  default     = 20
}

variable "copy_map_concurrency" {
  description = "Chunks copied at the same time by the copy pipeline."
  type        = number
  default     = 10
}

variable "copy_threads" {
  description = "Threads used inside one copy Lambda."
  type        = number
  default     = 32
}

variable "sfn_timeout_seconds" {
  description = "Overall timeout for one state machine execution."
  type        = number
  default     = 1800
}

variable "lambda_memory_mb" {
  description = "Memory for the Lambda functions."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 14
}

variable "work_retention_days" {
  description = "Days before temporary files under work/ expire."
  type        = number
  default     = 7
}

variable "openpyxl_layer_zip" {
  description = "Path to the openpyxl Lambda layer zip. Build it with scripts/build_layer.sh."
  type        = string
  default     = "build/openpyxl-layer.zip"
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default = {
    Project   = "file-transfer-demo"
    ManagedBy = "terraform"
  }
}
