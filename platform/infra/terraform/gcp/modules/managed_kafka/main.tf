# Managed Kafka for the authorization event stream (replaces Redpanda in the local stack); Flink jobs run on
# GKE or Dataproc in the same region and subnet.
variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "subnet_id" { type = string }
variable "kms_key_id" { type = string }

resource "google_managed_kafka_cluster" "events" {
  provider   = google-beta
  project    = var.project_id
  cluster_id = var.name
  location   = var.region
  capacity_config {
    vcpu_count   = 3
    memory_bytes = 3221225472
  }
  gcp_config {
    access_config {
      network_configs { subnet = var.subnet_id }
    }
    kms_key = var.kms_key_id
  }
}

resource "google_managed_kafka_topic" "topics" {
  provider           = google-beta
  for_each           = { "tx.raw" = 6, "tx.features" = 6, "tx.decisions" = 6, "tx.logins" = 3 }
  project            = var.project_id
  cluster            = google_managed_kafka_cluster.events.cluster_id
  location           = var.region
  topic_id           = replace(each.key, ".", "-")
  partition_count    = each.value
  replication_factor = 3
}
