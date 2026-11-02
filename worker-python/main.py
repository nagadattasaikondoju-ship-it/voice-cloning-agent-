import json
import logging
import time
import sys
from redis import Redis

from settings import REDIS_URL
from jobs import process_voice_clone_job, process_speech_job, delete_voice_job
import health

HEALTH_INTERVAL_S = 600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (Worker) %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("worker")


def run_worker_loop():
    logger.info(f"Connecting to Redis queue at {REDIS_URL}...")
    r = Redis.from_url(REDIS_URL, decode_responses=True)

    # Verify Redis connection
    try:
        r.ping()
        logger.info("Connected to Redis successfully. Listening for voice clone and speech synthesis jobs...")
    except Exception as e:
        logger.error(f"Could not connect to Redis: {e}. Worker will retry...")

    queues = ["voice_clone_jobs", "speech_jobs", "delete_voice_jobs"]
    last_health = 0.0

    while True:
        try:
            if time.time() - last_health > HEALTH_INTERVAL_S:
                last_health = time.time()
                try:
                    health.publish(r)
                except Exception as e:
                    logger.warning(f"Engine health check failed: {e}")

            # BRPOP blocks until an item is available in one of the queues
            item = r.brpop(queues, timeout=2)
            if not item:
                continue

            queue_name, raw_data = item
            job_data = json.loads(raw_data)

            logger.info(f"Received job from queue '{queue_name}'")

            if queue_name == "voice_clone_jobs":
                process_voice_clone_job(job_data)
            elif queue_name == "speech_jobs":
                process_speech_job(job_data)
            elif queue_name == "delete_voice_jobs":
                delete_voice_job(job_data)

        except KeyboardInterrupt:
            logger.info("Worker stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error in worker queue loop: {e}")
            time.sleep(2)


if __name__ == "__main__":
    run_worker_loop()
