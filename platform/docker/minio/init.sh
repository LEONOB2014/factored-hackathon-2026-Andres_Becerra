#!/bin/sh
# Buckets and identities for the object store.
#   bronze-worm     copy of record of bronze partitions + manifests (object lock, COMPLIANCE, 30 d in the demo)
#   audit-anchors   audit chain heads (object lock, COMPLIANCE, 30 d in the demo; years in production)
#   mlflow-artifacts models and datasets (versioned, no lock: registry stages are the control)
# COMPLIANCE mode means not even the root user can delete or shorten retention before expiry.
set -e
for i in $(seq 1 60); do
  mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 && break
  sleep 2
done
for b in bronze-worm audit-anchors; do
  mc mb --ignore-existing --with-lock local/$b
  mc retention set --default COMPLIANCE 30d local/$b
done
mc mb --ignore-existing --with-versioning local/mlflow-artifacts

cat > /tmp/platform.json <<POL
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:PutObject","s3:GetObject","s3:ListBucket","s3:GetObjectRetention","s3:GetBucketObjectLockConfiguration"],
  "Resource":["arn:aws:s3:::bronze-worm","arn:aws:s3:::bronze-worm/*","arn:aws:s3:::audit-anchors","arn:aws:s3:::audit-anchors/*"]}]}
POL
cat > /tmp/mlflow.json <<POL
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:*"],"Resource":["arn:aws:s3:::mlflow-artifacts","arn:aws:s3:::mlflow-artifacts/*"]}]}
POL
mc admin policy create local platform-writer /tmp/platform.json || true
mc admin policy create local mlflow-artifacts /tmp/mlflow.json || true
mc admin user add local "$MINIO_PLATFORM_USER" "$MINIO_PLATFORM_PASSWORD"
mc admin user add local "$MINIO_MLFLOW_USER" "$MINIO_MLFLOW_PASSWORD"
mc admin policy attach local platform-writer --user "$MINIO_PLATFORM_USER" || true
mc admin policy attach local mlflow-artifacts --user "$MINIO_MLFLOW_USER" || true
echo "minio-init done"
