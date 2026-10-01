# GitHub Actions -> Google Cloud with no key anywhere. The trust condition is the whole security boundary, so
# it is written to be read: this repository (by its immutable numeric id and by name), this owner (by id), the
# `main` branch, and only a job that runs in the `deploy` or `destroy` environment. Clauses are joined by AND,
# match exactly, and no value is a pattern. scripts/check_oidc_subjects.py compares this block with the
# expected text clause by clause; changing the boundary is changing that script in the same commit.
#
# What the condition does NOT do: GitHub decides who may start a run on `main` and whether the environment
# needs a reviewer. Those are repository settings (docs/DAY-ONE.md step 5), not Terraform.
locals {
  trusted_environments = ["deploy", "destroy"]

  trust_condition = join(" && ", [
    "assertion.repository_owner_id == '${var.github_owner_id}'",
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository == '${var.github_owner}/${var.github_repo}'",
    "assertion.ref == 'refs/heads/main'",
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
    "attribute.ref"                 = "assertion.ref"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.environment"         = "assertion.environment"
  }

  attribute_condition = local.trust_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# The pool admits only tokens that passed the provider's condition (this repository, `main`, an environment).
# Each service account is then bound to ONE environment: a job in `destroy` can become the destroyer and never
# the deployer, so disabling the deployer (the budget guard) cannot close the way to take the estate down.
resource "google_service_account_iam_member" "deployer_federation" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.environment/deploy"
}

resource "google_service_account_iam_member" "destroyer_federation" {
  service_account_id = google_service_account.destroyer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.environment/destroy"
}
