import json
import logging
import sys
import threading
import time

from redis import Redis

import health
import tts
from jobs import delete_voice_job, process_speech_job, process_voice_clone_job
from settings import REDIS_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (worker) %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("worker")

HANDLERS = {
    "voice_clone_jobs": process_voice_clone_job,
    "speech_jobs": process_speech_job,
    "delete_voice_jobs": delete_voice_job,
}
STATE = {"status": "loading", "problem": ""}


def heartbeat(r: Redis) -> None:
    while True:
        try:
            health.publish(r, STATE["status"], STATE["problem"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not publish health: {e}")
        time.sleep(30)


def main() -> None:
    # socket_timeout must exceed the BRPOP wait below, or idle waits raise TimeoutError.
    r = Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=30, socket_connect_timeout=10)
    while True:
        try:
            r.ping()
            break
        except Exception as e:  # noqa: BLE001
            logger.error(f"Redis not reachable at {REDIS_URL}: {e}; retrying in 3 s")
            time.sleep(3)

    threading.Thread(target=heartbeat, args=(r,), daemon=True).start()
    try:
        tts.load()
        STATE.update(status="ready", problem="")
    except Exception as e:  # noqa: BLE001
        logger.exception("Model failed to load")
        STATE.update(status="error", problem=f"Chatterbox failed to load: {e}")
    health.publish(r, STATE["status"], STATE["problem"])
    logger.info(f"Listening on {list(HANDLERS)}")

    while True:
        try:
            item = r.brpop(list(HANDLERS), timeout=5)
            if item:
                queue, raw = item
                HANDLERS[queue](json.loads(raw))
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            logger.error(f"Worker loop error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
