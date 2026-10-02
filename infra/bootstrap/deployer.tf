# The identities every CI run executes as. Two, with the same project roles, bound to different GitHub
# environments (wif.tf):
#   steward-deployer   `deploy` environment   apply; the budget guard disables it at the stop level
#   steward-destroyer  `destroy` environment  destroy; nothing disables it, so the estate can always be taken down
#
# These are strong identities, and this file says so. `projectIamAdmin` lets an identity grant itself any role
# and `serviceAccountTokenCreator` lets it become any service account in the project: whoever can run a job as
# the deployer has the project. The guard does NOT contain that (the deployer can alter the guard). What
# contains it: the trust condition (this repository, `main`, an environment), the required reviewer on the
# environments, a dedicated project with a ceiling and an end date, and `make destroy`. Narrowing the roles with
# IAM Conditions is done where it is cheap and testable: `projectIamAdmin` is conditioned to grant or revoke
# only `roles/bigquery.jobUser` (the one project role any layer grants; scripts/check_deployer_grants.py keeps the
# two lists equal), so the deployer can no longer grant itself a role. What remains is impersonation
# (`serviceAccountTokenCreator`): docs/DECISIONS.md B36.
resource "google_service_account" "deployer" {
  account_id   = "steward-deployer"
  display_name = "Steward deployer (GitHub Actions via Workload Identity Federation)"
  description  = "Runs terraform apply and evidence capture. Disabled by the budget guard at the stop level."

  depends_on = [google_project_service.api]
}

resource "google_service_account" "destroyer" {
  account_id   = "steward-destroyer"
  display_name = "Steward destroyer (GitHub Actions via Workload Identity Federation)"
  description  = "Runs terraform destroy and the sweep. Never disabled by the guard."

  depends_on = [google_project_service.api]
}

locals {
  ci_identities = {
    deployer  = google_service_account.deployer.email
    destroyer = google_service_account.destroyer.email
  }
}

resource "google_storage_bucket_iam_member" "ci_state" {
  for_each = local.ci_identities
  bucket   = google_storage_bucket.state.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${each.value}"
}

locals {
  # role -> which layer needs it. Project-scoped, in a dedicated project that is deleted at the end (CLAUDE.md).
  # Each one has a consumer in infra/*: remove the layer and the role goes with it.
  deployer_roles = {
    # estate (T011)
    "roles/bigquery.admin"            = "estate/governance: datasets, tables, row policies, scheduled queries; evidence queries"
    "roles/datacatalog.categoryAdmin" = "estate: policy-tag taxonomy and tags"
    "roles/storage.admin"             = "estate: landing bucket and the synthetic data in it"
    "roles/parametermanager.admin"    = "estate: published policy-tag ids (cross-layer values, never a remote-state read)"
    "roles/iam.serviceAccountAdmin"   = "estate: one service account per seat (no human identity is needed to show three roles)"
    # governance (T012)
    "roles/bigquerydatapolicy.admin"        = "governance: masking rules (data policies)"
    "roles/resourcemanager.projectIamAdmin" = "governance: jobUser for each seat. Conditioned: it may grant or revoke only the delegable roles (see the header)"
    "roles/iam.serviceAccountUser"          = "governance: scheduled queries run as the custodian's service account"
    "roles/iam.serviceAccountTokenCreator"  = "evidence: query as each seat's service account to capture the three role transcripts (python, not terraform)"
    # marketplace (T016)
    "roles/analyticshub.admin"   = "marketplace: exchange and listings"
    "roles/logging.configWriter" = "marketplace: Data Access audit sink"
    # assurance (T014, T015)
    "roles/dlp.admin"                         = "assurance: inspect template; sampled inspection for evidence"
    "roles/dataplex.admin"                    = "assurance: data quality scans; running them"
    "roles/datalineage.viewer"                = "assurance: read BigQuery job lineage for evidence"
    "roles/serviceusage.serviceUsageConsumer" = "every layer: use the project's quota"
  }
}

locals {
  # The project roles the layers actually grant (to seats). The deployer may delegate exactly these.
  delegable_roles = ["roles/bigquery.jobUser"]
  role_conditions = {
    "roles/resourcemanager.projectIamAdmin" = {
      title       = "grants-only-${replace(join("-", [for r in local.delegable_roles : basename(r)]), ".", "-")}"
      description = "Project IAM Admin, limited to granting and revoking the roles the layers hand out to seats."
      expression  = "api.getAttribute('iam.googleapis.com/modifiedGrantsByRole', []).hasOnly([${join(", ", [for r in local.delegable_roles : "'${r}'"])}])"
    }
  }
}

resource "google_project_iam_member" "ci" {
  for_each = { for pair in setproduct(keys(local.ci_identities), keys(local.deployer_roles)) : "${pair[0]}/${pair[1]}" => { who = pair[0], role = pair[1] } }
  project  = var.project_id
  role     = each.value.role
  member   = "serviceAccount:${local.ci_identities[each.value.who]}"

  dynamic "condition" {
    for_each = contains(keys(local.role_conditions), each.value.role) ? [local.role_conditions[each.value.role]] : []
    content {
      title       = condition.value.title
      description = condition.value.description
      expression  = condition.value.expression
    }
  }
}
