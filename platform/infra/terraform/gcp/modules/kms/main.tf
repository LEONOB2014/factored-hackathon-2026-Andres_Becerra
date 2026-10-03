# Customer-managed encryption keys (CMEK) per country and purpose. Keys stay in the residency region;
# rotation every 90 days; destroying a key version is how crypto-shredding is done at platform scale.
variable "project_id" { type = string }
variable "region" { type = string }
variable "country" { type = string }
variable "purposes" {
  type    = list(string)
  default = ["bigquery", "storage", "cloudsql", "audit"]
}

resource "google_kms_key_ring" "ring" {
  project  = var.project_id
  name     = "latam-${lower(var.country)}-ring"
  location = var.region
}

resource "google_kms_crypto_key" "keys" {
  for_each        = toset(var.purposes)
  name            = "${lower(var.country)}-${each.key}"
  key_ring        = google_kms_key_ring.ring.id
  rotation_period = "7776000s"
  purpose         = "ENCRYPT_DECRYPT"
  lifecycle { prevent_destroy = true }
}

output "key_ids" { value = { for k, v in google_kms_crypto_key.keys : k => v.id } }
