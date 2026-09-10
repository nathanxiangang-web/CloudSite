FROM python:3.12-alpine AS builder
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY cloudsite ./cloudsite
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/pip pip install ".[test]"

FROM python:3.12-alpine AS runner
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock ./
COPY cloudsite ./cloudsite
RUN pip install --no-cache-dir --no-deps -r requirements.lock && \
    pip install --no-cache-dir --no-deps .
EXPOSE 8000
CMD ["uvicorn", "cloudsite.main:app", "--host", "0.0.0.0", "--port", "8000"]
