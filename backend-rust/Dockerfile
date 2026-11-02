FROM rust:1.75-bookworm as builder

WORKDIR /usr/src/app
COPY Cargo.toml Cargo.lock* ./
# Cache dependency build
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release || true

COPY . .
RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates libssl3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /usr/src/app/target/release/intelligence-backend /app/intelligence-backend
COPY --from=builder /usr/src/app/migrations /app/migrations

EXPOSE 8080
CMD ["/app/intelligence-backend"]
