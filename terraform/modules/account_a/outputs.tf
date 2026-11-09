output "intake_bucket" {
  value = aws_s3_bucket.intake.bucket
}

output "landing_bucket" {
  value = aws_s3_bucket.landing.bucket
}

output "manifest_state_machine_arn" {
  value = aws_sfn_state_machine.manifest.arn
}

output "copy_state_machine_arn" {
  value = aws_sfn_state_machine.copy.arn
}
