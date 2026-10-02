# ==============================================================================
# Factored AI & Data Hackathon 2026
# Terraform - GCP Infrastructure
# ==============================================================================

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # For hackathon, use local state
  # In production, use GCS backend
  # backend "gcs" {
  #   bucket = "factored-hackathon-2026-tfstate"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ==============================================================================
# Variables
# ==============================================================================

variable "project_id" {
  description = "GCP Project ID"
  type        = string
  default     = "factored-hackathon-2026"
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

# ==============================================================================
# Cloud Storage - Data Lake
# ==============================================================================

resource "google_storage_bucket" "data_lake" {
  name     = "${var.project_id}-data-lake"
  location = var.region

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  labels = {
    environment = var.environment
    project     = "factored-hackathon-2026"
  }
}

# Data lake folder structure (Bronze/Silver/Gold)
resource "google_storage_bucket_object" "bronze_folder" {
  name    = "bronze/"
  content = " "
  bucket  = google_storage_bucket.data_lake.name
}

resource "google_storage_bucket_object" "silver_folder" {
  name    = "silver/"
  content = " "
  bucket  = google_storage_bucket.data_lake.name
}

resource "google_storage_bucket_object" "gold_folder" {
  name    = "gold/"
  content = " "
  bucket  = google_storage_bucket.data_lake.name
}

# ==============================================================================
# BigQuery - Data Warehouse
# ==============================================================================

resource "google_bigquery_dataset" "raw" {
  dataset_id  = "raw"
  description = "Bronze layer - raw ingested data"
  location    = var.region

  labels = {
    environment = var.environment
    layer       = "bronze"
  }
}

resource "google_bigquery_dataset" "clean" {
  dataset_id  = "clean"
  description = "Silver layer - cleaned and deduplicated data"
  location    = var.region

  labels = {
    environment = var.environment
    layer       = "silver"
  }
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id  = "analytics"
  description = "Gold layer - business analytics marts"
  location    = var.region

  labels = {
    environment = var.environment
    layer       = "gold"
  }
}

resource "google_bigquery_dataset" "ml" {
  dataset_id  = "ml"
  description = "ML features and predictions"
  location    = var.region

  labels = {
    environment = var.environment
    layer       = "ml"
  }
}

# ==============================================================================
# Cloud Run - Application Deployment
# ==============================================================================

resource "google_cloud_run_v2_service" "api" {
  name     = "banking-api"
  location = var.region

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/banking/api:latest"

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }
}

# ==============================================================================
# Artifact Registry - Container Images
# ==============================================================================

resource "google_artifact_registry_repository" "banking" {
  location      = var.region
  repository_id = "banking"
  format        = "DOCKER"
  description   = "Docker images for banking customer service system"
}

# ==============================================================================
# Outputs
# ==============================================================================

output "data_lake_bucket" {
  value = google_storage_bucket.data_lake.name
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "artifact_registry" {
  value = google_artifact_registry_repository.banking.name
}
