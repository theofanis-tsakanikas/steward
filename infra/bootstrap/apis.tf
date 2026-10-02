# Every API the later layers use, enabled once, here. A layer that needs a new API adds it to this list in the
# commit that adds the layer, so a reviewer sees the resource and the API side by side.
locals {
  apis = {
    # bootstrap itself
    "serviceusage.googleapis.com"         = "bootstrap"
    "cloudresourcemanager.googleapis.com" = "bootstrap"
    "iam.googleapis.com"                  = "bootstrap"
    "iamcredentials.googleapis.com"       = "bootstrap: Workload Identity Federation token exchange and seat impersonation"
    "sts.googleapis.com"                  = "bootstrap: Workload Identity Federation"
    "storage.googleapis.com"              = "bootstrap: state bucket; estate: landing bucket"
    "cloudbilling.googleapis.com"         = "bootstrap: budget"
    "billingbudgets.googleapis.com"       = "bootstrap: budget"
    "pubsub.googleapis.com"               = "bootstrap: budget notifications"
    "cloudfunctions.googleapis.com"       = "bootstrap: guard and reaper"
    "run.googleapis.com"                  = "bootstrap: guard and reaper (Cloud Run functions)"
    "cloudbuild.googleapis.com"           = "bootstrap: builds the functions"
    "artifactregistry.googleapis.com"     = "bootstrap: function images"
    "eventarc.googleapis.com"             = "bootstrap: Pub/Sub trigger of the guard"
    "cloudscheduler.googleapis.com"       = "bootstrap: daily reaper"
    "monitoring.googleapis.com"           = "bootstrap: email notification channels for the budget"
    "orgpolicy.googleapis.com"            = "bootstrap: the one project-level organization policy override (B53)"
    # estate
    "bigquery.googleapis.com"         = "estate"
    "datacatalog.googleapis.com"      = "estate: policy-tag taxonomy"
    "parametermanager.googleapis.com" = "estate: published policy-tag ids"
    # governance
    "bigquerydatapolicy.googleapis.com"   = "governance: masking rules"
    "bigquerydatatransfer.googleapis.com" = "governance: scheduled retention deletes"
    # marketplace
    "analyticshub.googleapis.com" = "marketplace: exchange and listings"
    "logging.googleapis.com"      = "marketplace: Data Access audit sink"
    # assurance
    "dlp.googleapis.com"         = "assurance: sensitive-data inspection"
    "dataplex.googleapis.com"    = "assurance: data quality scans"
    "datalineage.googleapis.com" = "assurance: lineage from BigQuery jobs"
  }
}

resource "google_project_service" "api" {
  for_each                   = local.apis
  service                    = each.key
  disable_on_destroy         = false
  disable_dependent_services = false
}
