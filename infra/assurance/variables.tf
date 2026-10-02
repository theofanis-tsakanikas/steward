variable "project_id" {
  description = "The dedicated GCP project for Steward."
  type        = string
}

variable "region" {
  description = "Region of the DLP inspect template (DLP processes in the region named in its parent) and of the Dataplex scans (a Dataplex location is a region: `eu` is refused, first apply 2026-10-02; the tables sit in the EU multi-region)."
  type        = string
  default     = "europe-west1"
}

variable "expires_at" {
  description = "ISO date after which the reaper destroys the estate."
  type        = string
}

variable "principals" {
  description = "Seat -> IAM member (serviceAccount:...), as in the governance layer (scripts/tfvars.py --layer assurance). A scan runs as its dataset's custodian seat. No default: a seat with no principal is a failed plan (doctrine 3)."
  type        = map(string)
}
