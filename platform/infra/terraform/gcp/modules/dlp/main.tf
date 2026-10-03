# Sensitive Data Protection inspect template with LATAM identifiers (mirrors latam_platform.pii_guard),
# used to scan buckets/BigQuery tables that must not contain personal data (knowledge, published zones).
variable "project_id" { type = string }
variable "region" { type = string }

resource "google_data_loss_prevention_inspect_template" "latam" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  display_name = "latam-pii"
  inspect_config {
    info_types { name = "EMAIL_ADDRESS" }
    info_types { name = "PHONE_NUMBER" }
    info_types { name = "CREDIT_CARD_NUMBER" }
    info_types { name = "IP_ADDRESS" }
    info_types { name = "MEXICO_CURP_NUMBER" }
    info_types { name = "BRAZIL_CPF_NUMBER" }
    info_types { name = "ARGENTINA_DNI_NUMBER" }
    info_types { name = "COLOMBIA_CDC_NUMBER" }
    custom_info_types {
      info_type { name = "MX_CLABE" }
      regex { pattern = "\\b\\d{18}\\b" }
      likelihood = "POSSIBLE"
    }
    min_likelihood = "LIKELY"
  }
}

output "inspect_template" { value = google_data_loss_prevention_inspect_template.latam.id }
