# Cost control (2 of 3, with the labels and the reaper): the alarm is created before anything that costs.
data "google_project" "this" {
  project_id = var.project_id

  # With user_project_override the read is billed to this project, whose Resource Manager API must be on.
  depends_on = [google_project_service.api]
}

# A new organization enforces secure-by-default policies, among them domain-restricted sharing
# (iam.allowedPolicyMemberDomains): only principals of the organization's own customer may appear in an IAM policy.
# Cloud Billing publishes budget notifications as billing-budget-alert@system.gserviceaccount.com, which is not of
# the organization, so a budget that notifies a topic is refused (FAILED_PRECONDITION). This lifts the restriction
# for THIS PROJECT ONLY; the organization keeps it, and the override is deleted with the project (DECISIONS B53).
# Needs roles/orgpolicy.policyAdmin on the applying identity (a local apply: the bootstrap layer is never run in CI).
resource "google_org_policy_policy" "budget_publisher" {
  name   = "projects/${var.project_id}/policies/iam.allowedPolicyMemberDomains"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      allow_all = "TRUE"
    }
  }

  depends_on = [google_project_service.api]
}

resource "google_pubsub_topic" "budget" {
  name = "steward-budget"

  # the budget grants Cloud Billing publish on this topic, which the organization policy refuses without the override
  depends_on = [google_project_service.api, google_org_policy_policy.budget_publisher]
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
    projects = ["projects/${data.google_project.this.number}"]
    # On a Free Trial the welcome credit pays every cent, so spend NET of credits is always zero and a budget that
    # subtracts credits would never alert and the guard would never fire. The default therefore measures the gross
    # usage cost. Set budget_counts_credits only on a paid account where net spend is the point (DECISIONS B49).
    credit_types_treatment = var.budget_counts_credits ? "INCLUDE_ALL_CREDITS" : "EXCLUDE_ALL_CREDITS"
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
  # month boundary, where the count restarts: docs/DECISIONS.md records it. costAmount is the gross usage cost
  # (credits not subtracted, see credit_types_treatment): the guard compares what usage would cost, whoever pays.
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
