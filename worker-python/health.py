"""Worker status published to Redis key `engine_health` (read by the Rust API's /api/engine).
Run `python health.py` to load the model and print a one-line report."""
import json
import time

import tts

REDIS_KEY = "engine_health"


def report(status: str, problem: str = "") -> dict:
    return {
        "ok": status == "ready",
        "status": status,  # loading | ready | error
        "engine": "chatterbox",
        "model": tts.MODEL,
        "model_label": tts.MODEL_LABEL,
        "device": tts.device(),
        "problem": problem,
        "checked_at": int(time.time()),
    }


def publish(redis_client, status: str, problem: str = "") -> None:
    # Expires so a dead worker shows as "not running" instead of stale "ready".
    redis_client.set(REDIS_KEY, json.dumps(report(status, problem)), ex=120)


if __name__ == "__main__":
    try:
        tts.load()
        r = report("ready")
    except Exception as e:  # noqa: BLE001
        r = report("error", str(e))
    print(json.dumps(r, indent=2))
