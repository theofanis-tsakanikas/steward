variable "project_id" {
  description = "The dedicated GCP project for Steward."
  type        = string
}

variable "region" {
  description = "Region of the DLP inspect template (DLP processes in the region named in its parent)."
  type        = string
  default     = "europe-west1"
}

variable "location" {
  description = "Location of the Dataplex scans: they must sit where the BigQuery datasets sit (EU multi-region, P2)."
  type        = string
  default     = "EU"
  validation {
    condition     = var.location == "EU"
    error_message = "Steward is EU-only (P2)."
  }
}

variable "expires_at" {
  description = "ISO date after which the reaper destroys the estate."
  type        = string
}
