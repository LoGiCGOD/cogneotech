FROM python:3.10-slim-buster AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.10-slim-buster
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]