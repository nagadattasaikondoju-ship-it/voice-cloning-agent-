FROM rust:1.89-bookworm AS builder
WORKDIR /usr/src/app

# Cache dependencies: build once with a stub main, then with the real sources.
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src

COPY src ./src
COPY migrations ./migrations
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /usr/src/app/target/release/intelligence-backend /app/intelligence-backend
EXPOSE 8080
CMD ["/app/intelligence-backend"]
