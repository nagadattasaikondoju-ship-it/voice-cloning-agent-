"""One Sarvam chat completion. Reads SARVAM_API_KEY from the environment or from .env."""
import os
from pathlib import Path

from sarvamai import SarvamAI

env_file = Path(__file__).with_name(".env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

api_key = os.environ.get("SARVAM_API_KEY")
if not api_key:
    raise SystemExit("SARVAM_API_KEY is not set. Put it in .env.")

client = SarvamAI(api_subscription_key=api_key)
response = client.chat.completions(
    model="sarvam-105b-conversations",
    messages=[{"role": "user", "content": "Say hello in one short sentence."}],
)
print(response.choices[0].message.content)
