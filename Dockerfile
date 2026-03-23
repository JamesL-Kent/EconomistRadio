FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RADIO_CONFIG_PATH=/app/config/radio.example.yaml

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY config /app/config

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "radio_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
