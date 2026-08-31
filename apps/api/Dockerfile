FROM python:3.12-alpine
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip pip install ".[test]"
COPY cloudsite ./cloudsite
RUN pip install --no-cache-dir --no-deps .
COPY tests ./tests
EXPOSE 8000
CMD ["uvicorn", "cloudsite.main:app", "--host", "0.0.0.0", "--port", "8000"]
