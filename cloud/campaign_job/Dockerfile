FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVO_CAMPAIGN_ROOT=/workspace/campaigns

WORKDIR /app

RUN pip install --no-cache-dir torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
       numpy==1.26.4 \
       pydantic==2.13.4 \
       google-adk==2.7.1 \
       google-genai==2.19.0 \
       google-cloud-storage==3.4.1 \
       google-cloud-firestore==2.21.0

COPY tools/realityci tools/realityci
COPY cloud/campaign_job/main.py cloud/campaign_job/main.py

ENTRYPOINT ["python", "cloud/campaign_job/main.py"]
