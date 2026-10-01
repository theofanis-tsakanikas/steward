variable "project_id" {
  description = "The dedicated GCP project for Steward."
  type        = string
}

variable "region" {
  description = "Region for regional resources."
  type        = string
  default     = "europe-west1"
}

variable "location" {
  description = "BigQuery / data-policy location. EU multi-region (P2)."
  type        = string
  default     = "EU"
  validation {
    condition     = var.location == "EU"
    error_message = "Steward is EU-only (P2)."
  }
}

variable "estate_version" {
  description = "Which published version of the estate parameter to read (the estate layer's publish_version)."
  type        = string
}

variable "expires_at" {
  description = "ISO date after which the reaper destroys the estate."
  type        = string
}
