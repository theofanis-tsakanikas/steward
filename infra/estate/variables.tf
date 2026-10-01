variable "project_id" {
  description = "The dedicated GCP project for Steward."
  type        = string
}

variable "region" {
  description = "Region for regional resources (Parameter Manager is global; BigQuery uses var.location)."
  type        = string
  default     = "europe-west1"
}

variable "location" {
  description = "BigQuery and taxonomy location. EU multi-region (docs/DECISIONS.md P2); permanent per dataset."
  type        = string
  default     = "EU"
  validation {
    condition     = var.location == "EU"
    error_message = "Steward is EU-only (P2). Changing it needs a decision record, not a variable."
  }
}

variable "publish_version" {
  description = "Version id of the published estate parameter. Parameter versions are immutable: bump on every apply that changes policy tags."
  type        = string
}

variable "expires_at" {
  description = "ISO date (YYYY-MM-DD) after which the reaper destroys the estate. Required: no estate stands without an end."
  type        = string
  validation {
    condition     = can(regex("^\\d{4}-\\d{2}-\\d{2}$", var.expires_at))
    error_message = "expires_at must be YYYY-MM-DD."
  }
}
