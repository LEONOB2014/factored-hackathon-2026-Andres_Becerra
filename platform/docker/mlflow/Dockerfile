# MLflow tracking server + model registry. Backend store: Postgres (pg-core/mlflow);
# artifacts: MinIO bucket mlflow-artifacts, proxied by the server (clients never get S3 credentials).
ARG MLFLOW_IMAGE=ghcr.io/mlflow/mlflow:v3.1.0
FROM ${MLFLOW_IMAGE}
RUN pip install --no-cache-dir psycopg2-binary boto3
