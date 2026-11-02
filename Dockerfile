FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    VETINSIGHT_DATA_DIR=/data VETINSIGHT_STATIC_DIR=/app/frontend-dist \
    VETINSIGHT_SECURE_COOKIES=1
WORKDIR /app/backend
COPY backend/requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY backend/app ./app
COPY --from=frontend /build/dist /app/frontend-dist
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
