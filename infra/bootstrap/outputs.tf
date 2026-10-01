output "state_bucket" {
  description = "Backend bucket for every other layer: terraform init -backend-config=\"bucket=<this>\" -backend-config=\"prefix=<layer>\"."
  value       = google_storage_bucket.state.name
}

output "github_repository_variables" {
  description = "The values CI cannot derive (it must authenticate before it can read anything). Set them as repository variables; nothing else is transcribed."
  value = {
    GCP_PROJECT_ID                 = var.project_id
    GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOYER_SERVICE_ACCOUNT   = google_service_account.deployer.email
    GCP_DESTROYER_SERVICE_ACCOUNT  = google_service_account.destroyer.email
  }
}

output "budget" {
  description = "Alert levels and where they go."
  value = {
    name         = google_billing_budget.steward.display_name
    total        = "${var.budget_total} ${var.budget_currency}"
    alert_at     = var.alert_at
    stop_at      = var.stop_at
    topic        = google_pubsub_topic.budget.id
    guard_active = var.enable_guard
  }
}

output "reenable_deployer" {
  description = "If the guard disabled the deployer, this is the one command that brings it back."
  value       = "gcloud iam service-accounts enable ${google_service_account.deployer.email} --project ${var.project_id}"
}
