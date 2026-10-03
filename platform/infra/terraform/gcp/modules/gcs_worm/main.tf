# Write-once buckets: bronze (copy of record), audit anchors, audit logs. The retention policy is LOCKED:
# once locked, nobody (including org admins) can shorten it or delete objects before expiry.
variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "retention_days" { type = number }
variable "kms_key_id" { type = string }
variable "lock" {
  type        = bool
  default     = false
  description = "Set true only after legal sign-off of retention_days: locking is irreversible."
}

resource "google_storage_bucket" "worm" {
  project                     = var.project_id
  name                        = var.name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning { enabled = true }
  retention_policy {
    retention_period = var.retention_days * 86400
    is_locked        = var.lock
  }
  encryption { default_kms_key_name = var.kms_key_id }
  logging { log_bucket = var.name }
}

output "bucket" { value = google_storage_bucket.worm.name }
