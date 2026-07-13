FROM node:24-alpine AS frontend
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html vite.config.ts tsconfig.json tsconfig.app.json tsconfig.node.json ./
COPY src ./src
ARG VITE_API_BASE_URL=
ARG VITE_PUBLIC_DEPLOYMENT=true
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_PUBLIC_DEPLOYMENT=$VITE_PUBLIC_DEPLOYMENT
RUN pnpm run build

FROM python:3.12-alpine AS runtime
ENV APP_HOST=0.0.0.0 \
    PORT=4173 \
    APP_DATA_DIR=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=frontend /app/dist ./dist
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY serve.py ./serve.py
RUN addgroup -S app && adduser -S app -G app && mkdir -p /data && chown -R app:app /app /data
USER app
VOLUME ["/data"]
EXPOSE 4173
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD wget -qO- "http://127.0.0.1:${PORT}/api/health" || exit 1
CMD ["python", "serve.py"]
