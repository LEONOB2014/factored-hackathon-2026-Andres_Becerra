# Managed Airflow (Cloud Composer 3) running the same DAGs as the local stack (platform/airflow/dags).
variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "network_id" { type = string }
variable "subnet_id" { type = string }
variable "kms_key_id" { type = string }
variable "service_account" { type = string }

resource "google_composer_environment" "airflow" {
  provider = google-beta
  project  = var.project_id
  name     = var.name
  region   = var.region
  config {
    software_config {
      image_version = "composer-3-airflow-3"
      env_variables = { LATAM_ENV = "prod" }
    }
    node_config {
      network         = var.network_id
      subnetwork      = var.subnet_id
      service_account = var.service_account
    }
    private_environment_config { enable_private_endpoint = true }
    encryption_config { kms_key_name = var.kms_key_id }
    environment_size = "ENVIRONMENT_SIZE_SMALL"
  }
}
