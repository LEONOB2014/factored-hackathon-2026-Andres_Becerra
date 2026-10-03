# Edge protection for the public API surface (scorer and, later, agent APIs behind API Gateway/Apigee).
variable "project_id" { type = string }
variable "name" { type = string }

resource "google_compute_security_policy" "api" {
  project = var.project_id
  name    = "${var.name}-api-armor"
  rule {
    action   = "deny(403)"
    priority = 1000
    match {
      expr { expression = "evaluatePreconfiguredWaf('sqli-v33-stable') || evaluatePreconfiguredWaf('xss-v33-stable')" }
    }
    description = "OWASP SQLi/XSS"
  }
  rule {
    action   = "throttle"
    priority = 2000
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      rate_limit_threshold {
        count        = 600
        interval_sec = 60
      }
    }
    description = "per-IP rate limit"
  }
  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "default"
  }
}
