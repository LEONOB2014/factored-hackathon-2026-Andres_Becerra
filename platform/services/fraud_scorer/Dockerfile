# Real-time fraud scorer (Kafka consumer + FastAPI behind Kong). Built from the repo root so the shared
# latam_platform library (model class used by the MLflow pyfunc) is importable.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*
COPY platform/services/fraud_scorer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY platform/libs/latam_platform /app/latam_platform
COPY platform/services/fraud_scorer/scorer.py /app/scorer.py
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
USER 65532
EXPOSE 8080 9108
CMD ["python", "scorer.py"]
