# Servo RealityCI control API on Cloud Run.
#
# The image carries the repository's tools/realityci package plus the FastAPI
# app. No credentials are baked in at build time: authentication is injected
# by Cloud Run (service account) or via SERVO_API_TOKEN for the demo bearer.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY cloud/control_api/requirements.txt cloud/control_api/requirements.txt
COPY cloud/control_api/requirements-gcs.txt cloud/control_api/requirements-gcs.txt
RUN pip install --no-cache-dir torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r cloud/control_api/requirements.txt \
    && pip install --no-cache-dir -r cloud/control_api/requirements-gcs.txt

# The API imports tools.realityci from the repository root (see main.py).
COPY tools/realityci tools/realityci
COPY tools/realityci/__init__.py tools/realityci/__init__.py
COPY tools/climate tools/climate
COPY cloud/control_api/app cloud/control_api/app

ENV SERVO_CAMPAIGN_ROOT=/workspace/campaigns
VOLUME ["/workspace"]

EXPOSE 8080
CMD ["uvicorn", "cloud.control_api.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
