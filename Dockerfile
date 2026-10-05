FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/src
CMD ["sh", "-c", "python -m uvicorn lending_library.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
