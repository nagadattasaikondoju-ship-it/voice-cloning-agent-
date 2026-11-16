#!/bin/sh
# Starts Redis (job queue only, nothing persistent), the voice worker and the API.
# If the worker or the API exits, the container exits so the host restarts it.
set -e
redis-server --daemonize yes --save "" --appendonly no --bind 127.0.0.1
cd /app/worker && python3 main.py &
WORKER=$!
/app/intelligence-backend &
API=$!
while kill -0 "$WORKER" 2>/dev/null && kill -0 "$API" 2>/dev/null; do sleep 5; done
echo "A process exited; stopping the container." >&2
exit 1
