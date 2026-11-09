output "lambda_role_arns" {
  description = "Roles that Account A's landing-zone bucket policy trusts."
  value       = [for r in aws_iam_role.lambda : r.arn]
}

output "batch_trigger_function" {
  value = aws_lambda_function.fn["batch_trigger"].function_name
}

output "loan_queue_url" {
  value = aws_sqs_queue.loan.url
}

output "dead_letter_queue_url" {
  value = aws_sqs_queue.dead_letter.url
}

output "loan_mapping_table" {
  value = aws_dynamodb_table.loan_mapping.name
}

output "doctype_mapping_table" {
  value = aws_dynamodb_table.doctype_mapping.name
}
