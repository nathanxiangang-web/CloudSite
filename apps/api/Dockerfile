FROM python:3.12-alpine
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[test]"
COPY cloudsite ./cloudsite
RUN pip install --no-cache-dir --no-deps .
COPY tests ./tests
EXPOSE 8000
CMD ["uvicorn", "cloudsite.main:app", "--host", "0.0.0.0", "--port", "8000"]
