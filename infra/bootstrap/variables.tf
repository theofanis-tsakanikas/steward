variable "project_id" {
  description = "The dedicated GCP project for Steward. Created and linked to billing by the author (docs/DAY-ONE.md steps 1-2)."
  type        = string
}

variable "region" {
  description = "Region for regional resources (Cloud Run functions, Scheduler, Pub/Sub). BigQuery uses the EU multi-region."
  type        = string
  default     = "europe-west1"
}

variable "location" {
  description = "Location of the state bucket. EU multi-region (docs/DECISIONS.md P2)."
  type        = string
  default     = "EU"
  validation {
    condition     = var.location == "EU"
    error_message = "Steward is EU-only (P2). Changing it needs a decision record, not a variable."
  }
}

variable "expires_at" {
  description = "ISO date (YYYY-MM-DD) the estate is meant to end by. The reaper deletes BigQuery datasets after it (only datasets; destroy.yml removes the rest). Required: no estate stands without an end."
  type        = string
  validation {
    condition     = can(regex("^\\d{4}-\\d{2}-\\d{2}$", var.expires_at))
    error_message = "expires_at must be YYYY-MM-DD."
  }
}

variable "billing_account_id" {
  description = "Billing account the project is linked to (XXXXXX-XXXXXX-XXXXXX). Needs Billing Account Administrator for the budget."
  type        = string
  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id looks like 012345-6789AB-CDEF01."
  }
}

variable "github_owner" {
  description = "GitHub user or organisation that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name."
  type        = string
}

variable "github_owner_id" {
  description = "Numeric GitHub owner id (gh api repos/OWNER/REPO --jq .owner.id). Pinned in the trust condition next to the repository id, so a transferred repository that reuses the old name is refused."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id is a number."
  }
}

variable "github_repository_id" {
  description = "Numeric GitHub repository id (gh api repos/OWNER/REPO --jq .id). The name is pinned as well, so a rename stops the deployer until the variables are updated: that is the intended failure."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id is a number."
  }
}

variable "budget_currency" {
  description = "Must equal the billing account's currency, or the Budget API refuses the budget."
  type        = string
  default     = "EUR"
}

variable "budget_total" {
  description = "The whole project's ceiling in budget_currency (CLAUDE.md: <= 50)."
  type        = number
  default     = 50
  validation {
    condition     = var.budget_total > 0 && var.budget_total <= 50
    error_message = "Steward's ceiling is 50. Raising it needs a decision record."
  }
}

variable "budget_counts_credits" {
  description = "false (default): the budget and the guard measure GROSS usage cost, which is what a Free Trial needs (credits would hold net spend at zero forever). true: subtract credits, for a paid account."
  type        = bool
  default     = false
}

variable "alert_at" {
  description = "Spend levels, in budget_currency, that send an alert (CLAUDE.md: 30 and 50). The guard stops at stop_at, which also sends one."
  type        = list(number)
  default     = [30, 50]
  validation {
    condition     = length(var.alert_at) > 0 && alltrue([for a in var.alert_at : a > 0 && a <= var.budget_total])
    error_message = "alert_at values must be positive and not above budget_total."
  }
}

variable "alert_emails" {
  description = "Addresses that receive budget alerts, in addition to the billing account's administrators."
  type        = list(string)
  default     = []
}

variable "stop_at" {
  description = "Spend level, in budget_currency, at which the guard disables the deployer. Below budget_total on purpose: budget data lags by hours, so a stop at the ceiling is already over it."
  type        = number
  default     = 45
  validation {
    condition     = var.stop_at > 0 && var.stop_at < var.budget_total
    error_message = "stop_at must be positive and strictly below budget_total."
  }
}

variable "enable_guard" {
  description = "The budget guard (disables the deploy path at the last alert level) and the reaper (deletes datasets past expires-at). Both are Cloud Run functions built by Cloud Build; turn off only to apply the rest first."
  type        = bool
  default     = true
}
