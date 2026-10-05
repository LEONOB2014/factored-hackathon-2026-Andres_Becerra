#!/usr/bin/env bash
# Build and deploy one regional BETA AID copilot on Cloud Run, holding only its countries' data.
#
#   copilot/deploy/cloudrun/deploy.sh mx northamerica-south1 MX
#   copilot/deploy/cloudrun/deploy.sh sa southamerica-east1  CO AR
#
# Needs: gcloud authenticated with a project set (Cloud Run, Artifact Registry and Cloud Build enabled; the default
# compute service account, which Cloud Build runs as, holding roles/cloudbuild.builds.builder), the demo
# snapshot and knowledge index under data/copilot/ (make copilot-snapshot, make copilot-kb). Run from the repo root.
set -euo pipefail

name="$1"; region="$2"; shift 2; countries=("$@")
project="$(gcloud config get-value project 2>/dev/null)"
repo="beta-aid"
image="${region}-docker.pkg.dev/${project}/${repo}/copilot-${name}:latest"
service="beta-aid-${name}"

# 1. this region's data only
(cd copilot && uv run python scripts/scope_snapshot.py "${countries[@]}" --name "${name}")

# 2. staged build context: code, knowledge documents, atlas, and this scope's data
stage="$(mktemp -d)"
trap 'rm -rf "${stage}"' EXIT
mkdir -p "${stage}/copilot" "${stage}/data"
cp -R copilot/src copilot/corpus "${stage}/copilot/"
find "${stage}" -name __pycache__ -prune -exec rm -rf {} +
cp -R knowledge "${stage}/knowledge"
cp eda/reports/dashboards/grain_atlas/grain_atlas.html "${stage}/atlas.html"
cp "data/copilot/scopes/${name}/snapshot.duckdb" "${stage}/data/snapshot.duckdb"
cp -R data/copilot/kb_index "${stage}/data/kb_index"
cp copilot/deploy/cloudrun/Dockerfile "${stage}/Dockerfile"

# 3. an Artifact Registry repository in the same region, so the image (and the data in it) stays there
gcloud artifacts repositories describe "${repo}" --location "${region}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "${repo}" --repository-format docker --location "${region}" \
       --description "BETA AID images (regional; contain demo data)"

# 4. a staging bucket pinned to the same region: the default Cloud Build bucket is US multi-region, and the build
#    source carries this region's data
number="$(gcloud projects describe "${project}" --format "value(projectNumber)")"
bucket="gs://beta-aid-build-${number}-${name}"
gcloud storage buckets describe "${bucket}" >/dev/null 2>&1 \
  || gcloud storage buckets create "${bucket}" --location "${region}" --uniform-bucket-level-access \
       --public-access-prevention

# 5. build in the same region and deploy one always-warm instance (sessions and actions live in the process)
gcloud builds submit "${stage}" --region "${region}" --tag "${image}" --timeout 1800 \
  --gcs-source-staging-dir "${bucket}/source" --gcs-log-dir "${bucket}/logs"
gcloud run deploy "${service}" --image "${image}" --region "${region}" \
  --allow-unauthenticated --min-instances 1 --max-instances 1 --cpu 1 --memory 2Gi --port 8080 \
  --set-env-vars "COPILOT_DEPLOYMENT=${service},COPILOT_REGION=${region}"
gcloud run services describe "${service}" --region "${region}" --format 'value(status.url)'
