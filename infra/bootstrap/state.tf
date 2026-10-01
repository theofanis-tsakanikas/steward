# The remote state of every other layer. Its name is derived, not published: CI must know where state lives
# before it can read anything, so it computes "<project id>-steward-tfstate" itself.
resource "google_storage_bucket" "state" {
  name                        = "${var.project_id}-steward-tfstate"
  location                    = var.location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 20
      with_state         = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    managed-by = "steward"
    purpose    = "terraform-state"
  }

  depends_on = [google_project_service.api]
}
