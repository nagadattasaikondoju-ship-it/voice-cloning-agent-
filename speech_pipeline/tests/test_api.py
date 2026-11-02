import io
import wave
import base64
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage.database import init_db

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    init_db()


def generate_test_wav_bytes(duration_s: float = 1.0, sr: int = 16000) -> bytes:
    """Generates a valid 16kHz mono 16-bit PCM WAV in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        # 440 Hz tone
        t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
        samples = (np.sin(2 * np.pi * 440 * t) * 16384).astype(np.int16)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def test_health_endpoint():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "whisper_info" in data


def test_upload_and_lifecycle():
    # 1. Upload audio file
    wav_bytes = generate_test_wav_bytes(duration_s=1.5)
    files = {"file": ("test_clip.wav", io.BytesIO(wav_bytes), "audio/wav")}
    res = client.post("/api/v1/recordings", files=files)
    assert res.status_code == 201
    upload_data = res.json()
    recording_id = upload_data["recording_id"]
    assert upload_data["status"] == "queued"
    assert upload_data["duration_seconds"] >= 1.0

    # 2. Get details
    res_details = client.get(f"/api/v1/recordings/{recording_id}")
    assert res_details.status_code == 200
    details = res_details.json()
    assert details["recording_id"] == recording_id
    assert details["status"] == "queued"

    # 3. Stream audio
    res_audio = client.get(f"/api/v1/recordings/{recording_id}/audio")
    assert res_audio.status_code == 200
    assert res_audio.headers["content-type"] == "audio/wav"

    # 4. Delete recording
    res_del = client.delete(f"/api/v1/recordings/{recording_id}")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # 5. Verify deleted
    res_check = client.get(f"/api/v1/recordings/{recording_id}")
    assert res_check.status_code == 404


def test_base64_upload():
    wav_bytes = generate_test_wav_bytes(duration_s=1.0)
    b64_str = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode("utf-8")

    res = client.post(
        "/api/v1/recordings",
        json={"audio_base64": b64_str, "filename": "base64_sample.wav"}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "queued"

    # Cleanup
    client.delete(f"/api/v1/recordings/{data['recording_id']}")
