# Operational Postgres (serving, online features, decisions, knowledge base with pgvector) and a SEPARATE
# instance for the audit store. Private IP only, CMEK, pgAudit, automated backups with PITR in-region.
variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "network_id" { type = string }
variable "kms_key_id" { type = string }
variable "tier" {
  type    = string
  default = "db-custom-2-7680"
}
variable "private_services_connection" { type = string }

resource "google_sql_database_instance" "pg" {
  project             = var.project_id
  name                = var.name
  region              = var.region
  database_version    = "POSTGRES_16"
  encryption_key_name = var.kms_key_id
  deletion_protection = true
  settings {
    tier              = var.tier
    availability_type = "REGIONAL"
    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      location                       = var.region
      backup_retention_settings { retained_backups = 30 }
    }
    database_flags {
      name  = "cloudsql.enable_pgaudit"
      value = "on"
    }
    database_flags {
      name  = "log_connections"
      value = "on"
    }
    insights_config { query_insights_enabled = true }
  }
  depends_on = [var.private_services_connection]
}

output "connection_name" { value = google_sql_database_instance.pg.connection_name }
output "private_ip" { value = google_sql_database_instance.pg.private_ip_address }
