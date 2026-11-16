# One container for free hosting (Render): Rust API + Python worker + Redis + the website.
# Postgres is external (e.g. Neon); set DATABASE_URL, JWT_SECRET and SARVAM_API_KEY.
# Local development keeps using docker-compose.yml with one container per service.

FROM rust:1.89-bookworm AS api
WORKDIR /src
COPY backend-rust/Cargo.toml backend-rust/Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src
COPY backend-rust/src ./src
COPY backend-rust/migrations ./migrations
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates ffmpeg redis-server python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker-python/requirements.txt worker/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r worker/requirements.txt
COPY worker-python/*.py worker/
COPY --from=api /src/target/release/intelligence-backend /app/intelligence-backend
COPY index.html styles.css robots.txt sitemap.xml public/
COPY assets public/assets
COPY frontend public/frontend
COPY deploy/start.sh /app/start.sh

ENV PUBLIC_DIR=/app/public \
    REDIS_URL=redis://127.0.0.1:6379/0 \
    TRUST_PROXY=true \
    PYTHONUNBUFFERED=1 \
    PORT=10000
EXPOSE 10000
CMD ["/app/start.sh"]
