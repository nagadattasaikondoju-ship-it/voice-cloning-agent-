"""
Engine self-check. The worker holds the API keys, so it is the only place that can tell
whether an engine will actually work. Results go to Redis key `engine_health`; the Rust
API shows them in /api/engines and refuses engines that are known to be broken.

Run by hand for a readable report:  python health.py
"""
import json
import logging
import time
from typing import Dict

import requests

from settings import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_BASE_URL,
    F5_SPACE,
    HF_TOKEN,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
    SPEECH_PIPELINE_URL,
)

logger = logging.getLogger(__name__)
REDIS_KEY = "engine_health"


def _result(ok: bool, problem: str = "", detail: str = "") -> Dict:
    return {"ok": ok, "problem": problem, "detail": detail, "checked_at": int(time.time())}


def check_minimax() -> Dict:
    if not MINIMAX_API_KEY:
        return _result(False, "MINIMAX_API_KEY is not set on the worker.")
    try:
        resp = requests.post(
            f"{MINIMAX_BASE_URL}/get_voice",
            headers={"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"},
            json={"voice_type": "voice_cloning"},
            timeout=20,
        )
        base = (resp.json() if resp.content else {}).get("base_resp") or {}
    except Exception as e:  # noqa: BLE001
        return _result(False, f"Cannot reach MiniMax at {MINIMAX_BASE_URL}: {e}")
    code = base.get("status_code", resp.status_code if resp.status_code >= 400 else 0)
    if code == 0:
        return _result(True, detail="API key accepted. Cloning also needs account verification and balance.")
    if code == 1004:
        return _result(
            False,
            "MiniMax rejected the API key (1004). Check the key, and that it matches the base URL: "
            "international keys use https://api.minimax.io/v1, mainland China keys https://api.minimaxi.com/v1.",
        )
    return _result(False, f"MiniMax error {code}: {base.get('status_msg')}")


def check_elevenlabs() -> Dict:
    if not ELEVENLABS_API_KEY:
        return _result(False, "ELEVENLABS_API_KEY is not set on the worker.")
    try:
        resp = requests.get(
            f"{ELEVENLABS_BASE_URL}/user/subscription", headers={"xi-api-key": ELEVENLABS_API_KEY}, timeout=20
        )
    except Exception as e:  # noqa: BLE001
        return _result(False, f"Cannot reach ElevenLabs: {e}")
    if resp.status_code == 401:
        detail = resp.text[:200]
        if "missing_permissions" in detail:
            return _result(
                False,
                "ElevenLabs key lacks permissions. Create a key with access to Voices (write), "
                "Text to Speech and User (read).",
            )
        return _result(False, "ElevenLabs rejected the API key (401).")
    if resp.status_code >= 400:
        return _result(False, f"ElevenLabs error {resp.status_code}: {resp.text[:200]}")
    sub = resp.json()
    tier = sub.get("tier", "?")
    used, limit = sub.get("character_count", 0), sub.get("character_limit", 0)
    if sub.get("can_use_instant_voice_cloning") is False:
        return _result(False, f"Your ElevenLabs plan ({tier}) does not include Instant Voice Cloning. Upgrade to Starter or above.")
    if limit and used >= limit:
        return _result(False, f"ElevenLabs credits used up ({used}/{limit}) on plan {tier}.")
    return _result(True, detail=f"Plan {tier}, {limit - used} credits left.")


def check_f5() -> Dict:
    try:
        resp = requests.get(f"https://huggingface.co/api/spaces/{F5_SPACE}/runtime", timeout=20)
        stage = resp.json().get("stage", "UNKNOWN") if resp.ok else f"HTTP {resp.status_code}"
    except Exception as e:  # noqa: BLE001
        return _result(False, f"Cannot reach Hugging Face: {e}")
    if stage not in ("RUNNING", "SLEEPING", "RUNNING_BUILDING", "APP_STARTING"):
        return _result(False, f"F5-TTS Space '{F5_SPACE}' is not running (stage: {stage}).")
    try:
        requests.get(f"{SPEECH_PIPELINE_URL}/api/v1/health", timeout=10).raise_for_status()
    except Exception:  # noqa: BLE001
        return _result(False, "F5 needs the Whisper speech pipeline to transcribe samples, and it is unreachable.")
    if not HF_TOKEN:
        return _result(
            True,
            detail="Works without a token, but anonymous use hits the ZeroGPU quota after a few requests. Set HF_TOKEN.",
        )
    return _result(True, detail="Hugging Face token set.")


CHECKS = {"minimax": check_minimax, "elevenlabs": check_elevenlabs, "f5": check_f5}


def run_checks() -> Dict[str, Dict]:
    return {name: fn() for name, fn in CHECKS.items()}


def publish(redis_client) -> Dict[str, Dict]:
    results = run_checks()
    redis_client.set(REDIS_KEY, json.dumps(results), ex=3600)
    for name, r in results.items():
        level = logging.INFO if r["ok"] else logging.WARNING
        logger.log(level, f"engine {name}: {'OK' if r['ok'] else 'NOT USABLE'} {r['problem'] or r['detail']}")
    return results


if __name__ == "__main__":
    for name, r in run_checks().items():
        print(f"{name:11} {'OK ' if r['ok'] else 'FAIL'}  {r['problem'] or r['detail']}")
