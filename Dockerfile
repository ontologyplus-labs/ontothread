FROM python:3.12.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md LICENSE DATA_NOTICE.md MANIFEST.in ./
COPY src ./src
RUN pip install --no-deps --no-build-isolation .
COPY examples ./examples
CMD ["uvicorn", "fig.api:app", "--host", "0.0.0.0", "--port", "8000"]
