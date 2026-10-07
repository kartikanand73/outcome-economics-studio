# ---- build the React UI ----
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- run the API and serve the built UI ----
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OES_DB_PATH=/data/scenarios.db OES_FRONTEND_DIST=/app/frontend/dist
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY samples/ samples/
COPY docs/ docs/
COPY --from=ui /ui/dist frontend/dist
VOLUME ["/data"]
EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
