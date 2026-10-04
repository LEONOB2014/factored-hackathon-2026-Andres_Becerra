# Residency-scoped BigQuery datasets for the analytics layer (dbt target bq_mx / bq_br):
#   published_<cc> : tables loaded from lakehouse gold/serving exports (no raw PII, tokens only)
#   analytics_<cc> : dbt views (models/bigquery) and authorized views
#   privacy_<cc>   : differentially private views (DP analysis rule budget enforced by BigQuery)
# Column-level security via a policy-tag taxonomy; row-level security by country via row access policies.
variable "project_id" { type = string }
variable "region" { type = string }
variable "country" { type = string }
variable "kms_key_id" { type = string }
variable "analyst_groups" {
  type        = map(string)
  description = "country code -> Google group allowed to read that country's rows"
}

locals { cc = lower(var.country) }

resource "google_bigquery_dataset" "ds" {
  for_each                    = toset(["published", "analytics", "privacy"])
  project                     = var.project_id
  dataset_id                  = "${each.key}_${local.cc}"
  location                    = var.region
  default_table_expiration_ms = null
  delete_contents_on_destroy  = false
  default_encryption_configuration { kms_key_name = var.kms_key_id }
  labels = { residency = local.cc, zone = each.key }
}

resource "google_data_catalog_taxonomy" "sensitivity" {
  provider               = google-beta
  project                = var.project_id
  region                 = var.region
  display_name           = "latam-${local.cc}-sensitivity"
  activated_policy_types = ["FINE_GRAINED_ACCESS_CONTROL"]
}

resource "google_data_catalog_policy_tag" "tags" {
  provider     = google-beta
  for_each     = toset(["restricted_pii", "confidential", "internal"])
  taxonomy     = google_data_catalog_taxonomy.sensitivity.id
  display_name = each.key
}

output "datasets" { value = { for k, v in google_bigquery_dataset.ds : k => v.dataset_id } }
output "policy_tags" { value = { for k, v in google_data_catalog_policy_tag.tags : k => v.id } }

# Analysts read only the analytics and DP views of their country, never the published tables directly.
resource "google_bigquery_dataset_iam_member" "analysts" {
  for_each   = { for pair in setproduct(keys(var.analyst_groups), ["analytics", "privacy"]) : "${pair[0]}-${pair[1]}" => pair }
  project    = var.project_id
  dataset_id = google_bigquery_dataset.ds[each.value[1]].dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "group:${var.analyst_groups[each.value[0]]}"
}
