terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.46"
    }
  }
  # Partial configuration: bucket and prefix come from `-backend-config` at init (written by the
  # bootstrap layer's outputs). Validation runs with -backend=false and needs neither.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
  # Cost control (1 of 3): every resource that takes labels carries the project and its expiry.
  default_labels = {
    project    = "steward"
    expires-at = var.expires_at
  }
}
