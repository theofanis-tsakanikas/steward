terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.46"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }
  # No backend, on purpose. The bootstrap layer creates the state bucket every other layer uses, so its own
  # state lives on the laptop that applies it (docs/DAY-ONE.md). `terraform.tfstate` is git-ignored; keep it
  # until `make destroy` has run, because it is the only record of what this layer made.
}

provider "google" {
  project = var.project_id
  region  = var.region
  # The Billing Budget API bills quota to a project, not to the caller.
  user_project_override = true
  billing_project       = var.project_id
  # Cost control (1 of 3): everything that takes labels carries the project and its end date.
  default_labels = {
    project    = "steward"
    expires-at = var.expires_at
  }
}
