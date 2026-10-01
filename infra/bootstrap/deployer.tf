# The identity every CI apply runs as. It starts with the state bucket and nothing else; each layer adds the
# roles that layer needs, here, in the commit that adds the layer. A failed apply on an access denial is a
# cheap, legible failure: it names the permission and the fix is one line with a reason.
resource "google_service_account" "deployer" {
  account_id   = "steward-deployer"
  display_name = "Steward deployer (GitHub Actions via Workload Identity Federation)"
  description  = "Runs terraform apply/destroy and evidence capture. Disabled by the budget guard at the last alert level."

  depends_on = [google_project_service.api]
}

resource "google_storage_bucket_iam_member" "deployer_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"
}

locals {
  # role -> why it exists. Project-scoped, in a dedicated project that is deleted at the end (CLAUDE.md).
  deployer_roles = {
    # estate (T011)
    "roles/bigquery.admin"            = "estate/governance: datasets, tables, row policies, scheduled queries; evidence queries"
    "roles/datacatalog.categoryAdmin" = "estate: policy-tag taxonomy and tags"
    "roles/storage.admin"             = "estate: landing bucket and the synthetic data in it"
    "roles/parametermanager.admin"    = "estate: published policy-tag ids (cross-layer values, never a remote-state read)"
    "roles/iam.serviceAccountAdmin"   = "estate: one service account per seat (no human identity is needed to show three roles)"
    # governance (T012)
    "roles/bigquerydatapolicy.admin"        = "governance: masking rules (data policies)"
    "roles/resourcemanager.projectIamAdmin" = "governance: jobUser for each seat. Powerful: it can grant itself anything; the compensating controls are the pinned trust condition, the 'deploy' environment, and the guard"
    "roles/iam.serviceAccountUser"          = "governance: scheduled queries run as the custodian's service account"
    "roles/iam.serviceAccountTokenCreator"  = "evidence: query as each seat's service account to capture the three role transcripts"
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

resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_roles
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.deployer.email}"
}
