output "intake_bucket" {
  value = module.account_a.intake_bucket
}

output "landing_bucket" {
  value = module.account_a.landing_bucket
}

output "manifest_state_machine_arn" {
  value = module.account_a.manifest_state_machine_arn
}

output "copy_state_machine_arn" {
  value = module.account_a.copy_state_machine_arn
}

output "batch_trigger_function" {
  value = module.account_b.batch_trigger_function
}

output "loan_queue_url" {
  value = module.account_b.loan_queue_url
}

output "loan_dead_letter_queue_url" {
  value = module.account_b.dead_letter_queue_url
}

output "loan_mapping_table" {
  value = module.account_b.loan_mapping_table
}

output "doctype_mapping_table" {
  value = module.account_b.doctype_mapping_table
}
