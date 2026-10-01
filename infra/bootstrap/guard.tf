# Cost control (3 of 3): the budget acts, the reaper sweeps. Two Cloud Run functions built from ./guard.
#   guard   - on the last budget alert, disables the deployer service account (reversible by hand)
#   reaper  - daily; deletes BigQuery datasets whose expires-at label has passed
locals {
  guard_enabled = var.enable_guard ? toset(["on"]) : toset([])
}

data "archive_file" "guard" {
  type        = "zip"
  source_dir  = "${path.module}/guard"
  output_path = "${path.module}/.build/guard.zip"
  excludes    = ["__pycache__", "*.pyc"]
}

resource "google_storage_bucket_object" "guard_source" {
  for_each = local.guard_enabled
  name     = "functions/guard-${data.archive_file.guard.output_md5}.zip"
  bucket   = google_storage_bucket.state.name
  source   = data.archive_file.guard.output_path
}

resource "google_service_account" "guard" {
  for_each     = local.guard_enabled
  account_id   = "steward-guard"
  display_name = "Steward budget guard and reaper"
  description  = "Disables the deployer at the last budget level; deletes expired datasets."

  depends_on = [google_project_service.api]
}

resource "google_service_account" "build" {
  for_each     = local.guard_enabled
  account_id   = "steward-build"
  display_name = "Steward function builds"
  description  = "Cloud Build identity for the guard and reaper (new projects no longer grant the default one build rights)."

  depends_on = [google_project_service.api]
}

resource "google_project_iam_member" "build" {
  for_each = local.guard_enabled
  project  = var.project_id
  role     = "roles/cloudbuild.builds.builder"
  member   = "serviceAccount:${google_service_account.build["on"].email}"
}

# The guard may disable the deployer and nothing else...
resource "google_service_account_iam_member" "guard_may_disable_deployer" {
  for_each           = local.guard_enabled
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.serviceAccountAdmin"
  member             = "serviceAccount:${google_service_account.guard["on"].email}"
}

# ...and the reaper may delete datasets (dataOwner includes bigquery.datasets.delete) and receive events.
resource "google_project_iam_member" "guard" {
  for_each = var.enable_guard ? toset(["roles/bigquery.dataOwner", "roles/eventarc.eventReceiver"]) : toset([])
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.guard["on"].email}"
}

resource "google_cloudfunctions2_function" "guard" {
  for_each = local.guard_enabled
  name     = "steward-budget-guard"
  location = var.region

  build_config {
    runtime         = "python312"
    entry_point     = "budget_guard"
    service_account = google_service_account.build["on"].id
    source {
      storage_source {
        bucket = google_storage_bucket.state.name
        object = google_storage_bucket_object.guard_source["on"].name
      }
    }
  }

  service_config {
    max_instance_count    = 1
    available_memory      = "256M"
    timeout_seconds       = 60
    service_account_email = google_service_account.guard["on"].email
    environment_variables = {
      PROJECT_ID     = var.project_id
      DEPLOYER_EMAIL = google_service_account.deployer.email
      GUARD_STOP_AT  = tostring(max(var.alert_at...))
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.budget.id
    retry_policy          = "RETRY_POLICY_DO_NOT_RETRY"
    service_account_email = google_service_account.guard["on"].email
  }

  depends_on = [google_project_iam_member.build, google_project_iam_member.guard]
}

resource "google_cloud_run_v2_service_iam_member" "guard_invoker" {
  for_each = local.guard_enabled
  location = var.region
  name     = google_cloudfunctions2_function.guard["on"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.guard["on"].email}"
}

resource "google_cloudfunctions2_function" "reaper" {
  for_each = local.guard_enabled
  name     = "steward-reaper"
  location = var.region

  build_config {
    runtime         = "python312"
    entry_point     = "reaper"
    service_account = google_service_account.build["on"].id
    source {
      storage_source {
        bucket = google_storage_bucket.state.name
        object = google_storage_bucket_object.guard_source["on"].name
      }
    }
  }

  service_config {
    max_instance_count    = 1
    available_memory      = "256M"
    timeout_seconds       = 120
    service_account_email = google_service_account.guard["on"].email
    ingress_settings      = "ALLOW_ALL"
    environment_variables = {
      PROJECT_ID = var.project_id
    }
  }

  depends_on = [google_project_iam_member.build, google_project_iam_member.guard]
}

resource "google_cloud_run_v2_service_iam_member" "reaper_invoker" {
  for_each = local.guard_enabled
  location = var.region
  name     = google_cloudfunctions2_function.reaper["on"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.guard["on"].email}"
}

resource "google_cloud_scheduler_job" "reaper" {
  for_each  = local.guard_enabled
  name      = "steward-reaper-daily"
  region    = var.region
  schedule  = "17 5 * * *"
  time_zone = "Etc/UTC"

  http_target {
    uri         = google_cloudfunctions2_function.reaper["on"].service_config[0].uri
    http_method = "POST"
    oidc_token {
      service_account_email = google_service_account.guard["on"].email
      audience              = google_cloudfunctions2_function.reaper["on"].service_config[0].uri
    }
  }

  depends_on = [google_project_service.api]
}
