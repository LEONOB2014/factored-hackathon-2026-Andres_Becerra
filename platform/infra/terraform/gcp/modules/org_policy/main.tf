# Residency guardrail at the resource-hierarchy level: resources can only be created in the allowed
# locations (mirrors platform/policies/residency.yaml). Applied per project/folder.
variable "parent" {
  type        = string
  description = "projects/<id> or folders/<id>"
}
variable "allowed_locations" { type = list(string) }

resource "google_org_policy_policy" "resource_locations" {
  name   = "${var.parent}/policies/gcp.resourceLocations"
  parent = var.parent
  spec {
    rules {
      values { allowed_values = [for l in var.allowed_locations : "in:${l}-locations"] }
    }
  }
}

resource "google_org_policy_policy" "no_public_buckets" {
  name   = "${var.parent}/policies/storage.publicAccessPrevention"
  parent = var.parent
  spec {
    rules { enforce = "TRUE" }
  }
}
