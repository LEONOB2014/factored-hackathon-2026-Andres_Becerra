# Cloud Audit Logs (admin + data access) routed to a locked WORM bucket in-region, so platform-level
# actions (IAM changes, dataset reads, KMS use) have the same tamper-evidence as the application ledger.
variable "project_id" { type = string }
variable "destination_bucket" { type = string }

resource "google_project_iam_audit_config" "all" {
  project = var.project_id
  service = "allServices"
  audit_log_config { log_type = "ADMIN_READ" }
  audit_log_config { log_type = "DATA_READ" }
  audit_log_config { log_type = "DATA_WRITE" }
}

resource "google_logging_project_sink" "audit_to_worm" {
  project                = var.project_id
  name                   = "audit-logs-to-worm"
  destination            = "storage.googleapis.com/${var.destination_bucket}"
  filter                 = "logName:\"cloudaudit.googleapis.com\""
  unique_writer_identity = true
}

output "writer_identity" { value = google_logging_project_sink.audit_to_worm.writer_identity }
