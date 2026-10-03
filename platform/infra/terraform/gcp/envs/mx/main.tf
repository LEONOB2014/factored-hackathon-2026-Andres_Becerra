# Mexico: in-country region (Querétaro). LFPDPPP 2025, CNBV.
# NOT APPLIED: validated offline (terraform validate / tflint). Apply only after legal sign-off of residency
# and retention, with a remote state backend (GCS, CMEK) configured in backend.tf.
variable "project_id" { type = string }
variable "access_policy_id" {
  type    = string
  default = null
}
variable "composer_service_account" { type = string }
variable "analyst_group" { type = string }

locals {
  region  = "northamerica-south1"
  country = "MX"
  name    = "latam-mx"
}

provider "google" {
  project = var.project_id
  region  = local.region
}

provider "google-beta" {
  project = var.project_id
  region  = local.region
}

module "org_policy" {
  source            = "../../modules/org_policy"
  parent            = "projects/${var.project_id}"
  allowed_locations = [local.region]
}

module "network" {
  source           = "../../modules/network"
  project_id       = var.project_id
  region           = local.region
  name             = local.name
  access_policy_id = var.access_policy_id
}

module "kms" {
  source     = "../../modules/kms"
  project_id = var.project_id
  region     = local.region
  country    = local.country
}

module "bronze_worm" {
  source         = "../../modules/gcs_worm"
  project_id     = var.project_id
  region         = local.region
  name           = "${local.name}-bronze-worm"
  retention_days = 3650
  kms_key_id     = module.kms.key_ids["storage"]
}

module "audit_worm" {
  source         = "../../modules/gcs_worm"
  project_id     = var.project_id
  region         = local.region
  name           = "${local.name}-audit-worm"
  retention_days = 3650
  kms_key_id     = module.kms.key_ids["audit"]
}

module "audit_logging" {
  source             = "../../modules/audit_logging"
  project_id         = var.project_id
  destination_bucket = module.audit_worm.bucket
}

module "bigquery" {
  source         = "../../modules/bigquery"
  project_id     = var.project_id
  region         = local.region
  country        = local.country
  kms_key_id     = module.kms.key_ids["bigquery"]
  analyst_groups = { (local.country) = var.analyst_group }
}

module "pg_serving" {
  source                      = "../../modules/cloudsql_postgres"
  project_id                  = var.project_id
  region                      = local.region
  name                        = "${local.name}-pg-serving"
  network_id                  = module.network.network_id
  kms_key_id                  = module.kms.key_ids["cloudsql"]
  private_services_connection = module.network.private_services_connection
}

module "pg_audit" {
  source                      = "../../modules/cloudsql_postgres"
  project_id                  = var.project_id
  region                      = local.region
  name                        = "${local.name}-pg-audit"
  network_id                  = module.network.network_id
  kms_key_id                  = module.kms.key_ids["audit"]
  tier                        = "db-custom-1-3840"
  private_services_connection = module.network.private_services_connection
}

module "composer" {
  source          = "../../modules/composer"
  project_id      = var.project_id
  region          = local.region
  name            = "${local.name}-airflow"
  network_id      = module.network.network_id
  subnet_id       = module.network.subnet_id
  kms_key_id      = module.kms.key_ids["storage"]
  service_account = var.composer_service_account
}

module "kafka" {
  source     = "../../modules/managed_kafka"
  project_id = var.project_id
  region     = local.region
  name       = "${local.name}-events"
  subnet_id  = module.network.subnet_id
  kms_key_id = module.kms.key_ids["storage"]
}

module "dlp" {
  source     = "../../modules/dlp"
  project_id = var.project_id
  region     = local.region
}

module "edge" {
  source     = "../../modules/edge"
  project_id = var.project_id
  name       = local.name
}
