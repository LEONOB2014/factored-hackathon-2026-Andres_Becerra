# Airflow 3 image for the LATAM platform.
# Workloads run in isolated virtualenvs so their dependencies never fight Airflow's constraints:
#   /opt/dbt-venv       dbt-core + dbt-duckdb (Cosmos calls this dbt executable)
#   /opt/platform-venv  latam_platform library + ML/KB/privacy deps (@task.external_python)
ARG AIRFLOW_IMAGE=apache/airflow:3.1.0-python3.12
FROM ${AIRFLOW_IMAGE}

USER root
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*
USER airflow

# Airflow-side providers (installed against Airflow's constraints).
RUN pip install --no-cache-dir \
      "astronomer-cosmos>=1.10" \
      "apache-airflow-providers-openlineage" \
      "apache-airflow-providers-postgres" \
      "apache-airflow-providers-amazon" \
      "pyyaml"

# dbt in its own venv.
RUN python -m venv /opt/airflow/dbt-venv \
    && /opt/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-core>=1.10,<2" "dbt-duckdb>=1.10" "openlineage-dbt"

# Platform / ML venv (CPU torch keeps the image small enough for a laptop).
COPY requirements-platform.txt /tmp/requirements-platform.txt
RUN python -m venv /opt/airflow/platform-venv \
    && /opt/airflow/platform-venv/bin/pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && /opt/airflow/platform-venv/bin/pip install --no-cache-dir -r /tmp/requirements-platform.txt \
    && /opt/airflow/platform-venv/bin/python -m spacy download en_core_web_sm \
    && /opt/airflow/platform-venv/bin/python -m spacy download es_core_news_sm \
    && echo "/opt/latam/platform/libs" > $(/opt/airflow/platform-venv/bin/python -c "import site; print(site.getsitepackages()[0])")/latam_platform.pth

# Airflow's external-python runner serializes task arguments with pendulum/cloudpickle inside the target venv.
RUN /opt/airflow/platform-venv/bin/pip install --no-cache-dir pendulum cloudpickle

# Owned by the airflow user so the named volume mounted here inherits writable ownership.
RUN mkdir -p /opt/airflow/config

ENV LATAM_REPO_ROOT=/opt/latam \
    LATAM_DATA_DIR=/opt/latam/data \
    LATAM_LAKE_DIR=/opt/latam/data/lake \
    LATAM_DUCKDB_PATH=/opt/latam/data/lake/lakehouse.duckdb \
    DBT_PROFILES_DIR=/opt/latam/platform/dbt \
    HF_HOME=/opt/latam/data/models_cache
