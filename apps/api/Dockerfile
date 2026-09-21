ARG DRIVER115_VERSION=v1.3.5

# --------------------------------------------------
# 1. Build 115driver CLI
# --------------------------------------------------
FROM golang:1.23-alpine AS driver-builder
ARG DRIVER115_VERSION
RUN go install github.com/SheltonZhu/115driver/cmd/115driver@${DRIVER115_VERSION}

# --------------------------------------------------
# 2. Build CloudSite Python
# --------------------------------------------------
FROM python:3.12-alpine AS builder
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY cloudsite ./cloudsite
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/pip pip install ".[test]"

# --------------------------------------------------
# 3. Final runtime image
# --------------------------------------------------
FROM python:3.12-alpine AS runner
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
COPY cloudsite ./cloudsite
RUN pip install --no-cache-dir --no-deps -r requirements.lock && \
    pip install --no-cache-dir --no-deps .

COPY --from=driver-builder \
    /go/bin/115driver \
    /usr/local/bin/115driver
RUN chmod +x /usr/local/bin/115driver

EXPOSE 8000
CMD ["uvicorn", "cloudsite.main:app", "--host", "0.0.0.0", "--port", "8000"]
