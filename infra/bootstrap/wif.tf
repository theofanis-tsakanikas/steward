# GitHub Actions -> Google Cloud with no key anywhere. The trust condition is the whole security boundary, so
# it is written to be read: this repository (by its immutable numeric id, not only its name), this owner (by
# id), and only a job that runs in the `deploy` or `destroy` environment. No value contains a wildcard
# (scripts/check_oidc_subjects.py fails CI if one ever does).
locals {
  trusted_environments = ["deploy", "destroy"]

  trust_condition = join(" && ", [
    "assertion.repository_owner_id == '${var.github_owner_id}'",
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository == '${var.github_owner}/${var.github_repo}'",
    "assertion.environment in [${join(", ", [for e in local.trusted_environments : "'${e}'"])}]",
  ])
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "steward-github"
  display_name              = "Steward GitHub Actions"
  description               = "Federated identity for ${var.github_owner}/${var.github_repo} workflows. No service-account key exists."

  depends_on = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.environment"         = "assertion.environment"
  }

  attribute_condition = local.trust_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Only identities that passed the provider's condition AND belong to this repository id may become the deployer.
resource "google_service_account_iam_member" "deployer_federation" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}
