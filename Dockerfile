FROM node:22-alpine AS web
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY index.html vite.config.js ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STOCK_LENS_DATA_DIR=/app/data
WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt && useradd --uid 10001 --create-home stocklens
COPY backend ./backend
COPY validation/audit.json ./validation/audit.json
COPY --from=web /web/dist ./dist
RUN mkdir /app/data && chown stocklens:stocklens /app/data
USER stocklens
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=3)"
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers"]
