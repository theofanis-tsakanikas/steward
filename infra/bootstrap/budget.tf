# Cost control (2 of 3, with the labels and the reaper): the alarm is created before anything that costs.
data "google_project" "this" {
  project_id = var.project_id

  # With user_project_override the read is billed to this project, whose Resource Manager API must be on.
  depends_on = [google_project_service.api]
}

resource "google_pubsub_topic" "budget" {
  name = "steward-budget"

  depends_on = [google_project_service.api]
}

resource "google_monitoring_notification_channel" "email" {
  for_each     = toset(var.alert_emails)
  display_name = "Steward budget alerts: ${each.key}"
  type         = "email"
  labels = {
    email_address = each.key
  }

  depends_on = [google_project_service.api]
}

resource "google_billing_budget" "steward" {
  billing_account = var.billing_account_id
  display_name    = "steward (${var.project_id})"

  budget_filter {
    projects               = ["projects/${data.google_project.this.number}"]
    credit_types_treatment = "INCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.budget_total)
    }
  }

  # "30" and "50" are spend levels, not percentages: the thresholds are derived so the alert levels stay what
  # the variable says they are. The guard's stop level sends an alert too.
  #
  # The period is the default, one calendar month. The estate lives days, so it is one month except across a
  # month boundary, where the count restarts: docs/DECISIONS.md records it. costAmount includes credits
  # (INCLUDE_ALL_CREDITS): the guard compares what would actually be billed.
  dynamic "threshold_rules" {
    for_each = toset(concat(var.alert_at, [var.stop_at]))
    content {
      threshold_percent = threshold_rules.value / var.budget_total
      spend_basis       = "CURRENT_SPEND"
    }
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    pubsub_topic                     = google_pubsub_topic.budget.id
    schema_version                   = "1.0"
    monitoring_notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.api]
}
