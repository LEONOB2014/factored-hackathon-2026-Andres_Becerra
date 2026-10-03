# Private network per residency region. No public IPs on data services; Google APIs via Private Service
# Connect; data services live inside a VPC Service Controls perimeter so data cannot be exfiltrated to
# projects outside it even with valid credentials.
variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "access_policy_id" {
  type        = string
  default     = null
  description = "Access Context Manager policy id (org-level). Null skips the perimeter (sandbox projects)."
}

resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = "${var.name}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "data" {
  project                  = var.project_id
  name                     = "${var.name}-data"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = "10.10.0.0/20"
  private_ip_google_access = true
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 1.0
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "${var.name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

resource "google_compute_firewall" "deny_all_ingress" {
  project   = var.project_id
  name      = "${var.name}-deny-all-ingress"
  network   = google_compute_network.vpc.id
  direction = "INGRESS"
  priority  = 65534
  deny { protocol = "all" }
  source_ranges = ["0.0.0.0/0"]
}

data "google_project" "this" { project_id = var.project_id }

resource "google_access_context_manager_service_perimeter" "data" {
  count  = var.access_policy_id == null ? 0 : 1
  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/${replace(var.name, "-", "_")}_data"
  title  = "${var.name} data perimeter"
  status {
    resources = ["projects/${data.google_project.this.number}"]
    restricted_services = ["bigquery.googleapis.com", "storage.googleapis.com", "sqladmin.googleapis.com",
    "composer.googleapis.com", "dlp.googleapis.com", "managedkafka.googleapis.com"]
  }
}

output "network_id" { value = google_compute_network.vpc.id }
output "subnet_id" { value = google_compute_subnetwork.data.id }
output "private_services_connection" { value = google_service_networking_connection.private_services.id }
