# Production-Quality Local-First Speech-to-Text Pipeline

A high-performance, local-first speech-to-text pipeline in Python 3.11+ powered by **Silero VAD** voice activity detection and **faster-whisper** automatic speech recognition.

---

## Key Capabilities

1. **Audio Ingestion & Normalization**: Automatically converts any audio format (WAV, MP3, M4A, OGG, WEBM) to 16,000 Hz mono 16-bit PCM WAV with peak volume normalization.
2. **Whole-Audio Silero VAD**: Runs Voice Activity Detection across the complete audio first (not micro-chunks) to preserve phonetic continuity.
3. **5-Second Chunking with Overlap**:
   - Merges speech regions separated by `< 400ms` silence.
   - Preserves `200ms` speech padding before and after word onsets/offsets.
   - Splits long speech into clean `<= 5.0s` chunks at natural silence dips, or with `200ms` overlap if no dip exists.
4. **Local faster-whisper Inference**:
   - Uses `large-v3` with `float16` when NVIDIA CUDA is detected.
   - Automatically falls back to `base` (or `small`) with `int8` on CPU.
5. **Exact Timeline Restoration**:
   - Maps each chunk's local timestamps back to original recording seconds.
   - Supports word-level timestamps (`word_timestamps=True`).
6. **Smart Transcript Formatting**:
   - Inserts paragraph breaks on pauses longer than `1.5s`.
   - Filters repetitive hallucinated phrases (e.g. "Thank you.", "Thanks for watching.") on low-energy audio.
7. **Storage & Non-Blocking API**:
   - SQLite with WAL mode indexing recordings, chunks, and segments.
   - Asynchronous background jobs via FastAPI `BackgroundTasks`.
   - Audio streaming endpoint and complete cleanup.
8. **Modern Web Interface**: Built-in dark mode UI with live microphone capture visualizer and timestamped segment audio seeking.

---

## Architecture Overview

```
[Audio Input (Upload or Microphone)]
              │
              ▼
[Preprocess: 16kHz Mono PCM WAV + Peak Normalization]
              │
              ▼
[Silero VAD: Complete Audio Speech Detection]
              │
              ▼
[Clean Speech Chunks (<= 5s, 200ms overlap, 200ms padding)]
              │
              ▼
[faster-whisper ASR: GPU large-v3 or CPU base/small]
              │
              ▼
[Timeline Mapping: Chunk Offset -> Global Recording Timestamp]
              │
              ▼
[Transcript Postprocessing: Paragraph Breaks (>1.5s) & Hallucination Filter]
              │
              ▼
[SQLite Storage + Storage Files + REST API + Web UI]
```

---

## Directory Structure

```
speech_pipeline/
  app/
    main.py                 # FastAPI application & lifespan
    config.py               # Settings & GPU/CPU device resolution
    schemas.py              # Pydantic request & response models
    audio/
      recorder.py           # Microphone capture & base64 ingestion
      preprocess.py         # Resample, mono conversion, peak normalization
      vad.py                # Silero VAD & 5-second chunking
      timestamps.py         # Timeline restoration & transcript formatting
    asr/
      whisper_engine.py     # faster-whisper singleton engine
      transcribe.py         # End-to-end transcription coordinator
    storage/
      database.py           # SQLite WAL connection & CRUD
      files.py              # Directory layout & file persistence
    api/
      routes.py             # REST API endpoints
  web/
    index.html              # Modern web UI with live recording & player
  tests/
    test_vad.py             # VAD merging & chunking tests
    test_transcription.py   # Timestamp mapping & paragraph break tests
    test_api.py             # API lifecycle & streaming integration tests
  requirements.txt          # Pinned compatible dependencies
  Dockerfile                # Containerized deployment with ffmpeg
  .env.example              # Configuration template
  README.md
```

---

## Quickstart & Installation

### 1. Prerequisites
- Python 3.11+
- `ffmpeg` installed and in your system PATH (recommended for audio decoding)

### 2. Setup Virtual Environment
```bash
cd speech_pipeline
python -m venv venv

# On Linux / macOS:
source venv/bin/activate

# On Windows:
.\venv\Scripts\activate

pip install -r requirements.txt
```

### 3. GPU vs CPU Configuration

The pipeline automatically configures hardware:
- **NVIDIA GPU (CUDA)**: Uses model `large-v3` with `float16` compute type for maximum accuracy.
- **CPU**: Uses model `base` with `int8` quantization for fast, low-memory execution.

To explicitly force a mode, edit `.env`:
```env
WHISPER_DEVICE=cuda      # or 'cpu'
WHISPER_MODEL_GPU=large-v3
WHISPER_MODEL_CPU=base
WHISPER_COMPUTE_TYPE=auto
```

### 4. Run the Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **`http://localhost:8000`** in your browser to use the Web UI.

---

## API Reference & Examples

### Ingest Audio (Upload File)
```bash
curl -X POST "http://localhost:8000/api/v1/recordings" \
  -F "file=@sample.mp3" \
  -F "language=en"
```

**Response (HTTP 201):**
```json
{
  "recording_id": "4b684cb3-078c-4a37-b95a-c5adab3d1f02",
  "status": "queued",
  "duration_seconds": 18.42,
  "message": "Audio successfully converted to 16kHz mono WAV and queued."
}
```

---

### Ingest Base64 Audio (From Browser MediaRecorder)
```bash
curl -X POST "http://localhost:8000/api/v1/recordings" \
  -H "Content-Type: application/json" \
  -d '{
    "audio_base64": "data:audio/wav;base64,UklGRi...",
    "filename": "microphone.wav"
  }'
```

---

### Start Transcription (Non-Blocking Background Job)
```bash
curl -X POST "http://localhost:8000/api/v1/recordings/4b684cb3-078c-4a37-b95a-c5adab3d1f02/process"
```

**Response (HTTP 200):**
```json
{
  "recording_id": "4b684cb3-078c-4a37-b95a-c5adab3d1f02",
  "status": "processing",
  "message": "Background transcription job successfully initiated."
}
```

---

### Poll Status & Get Full Timestamped Results
```bash
curl -X GET "http://localhost:8000/api/v1/recordings/4b684cb3-078c-4a37-b95a-c5adab3d1f02"
```

**Complete Output Example:**
```json
{
  "recording_id": "4b684cb3-078c-4a37-b95a-c5adab3d1f02",
  "status": "completed",
  "duration_seconds": 18.42,
  "language": "en",
  "language_probability": 0.99,
  "full_transcript": "Welcome to our speech pipeline demonstration.\n\nNotice how the timestamps accurately align with the speech segments, even when long pauses are removed by Silero VAD.",
  "segments": [
    {
      "segment_id": 1,
      "start": 0.42,
      "end": 3.85,
      "text": "Welcome to our speech pipeline demonstration.",
      "confidence": 0.96,
      "words": [
        {"word": "Welcome", "start": 0.42, "end": 0.88, "probability": 0.99},
        {"word": "to", "start": 0.90, "end": 1.05, "probability": 0.98},
        {"word": "our", "start": 1.08, "end": 1.25, "probability": 0.97},
        {"word": "speech", "start": 1.30, "end": 1.72, "probability": 0.98},
        {"word": "pipeline", "start": 1.75, "end": 2.30, "probability": 0.95},
        {"word": "demonstration.", "start": 2.35, "end": 3.85, "probability": 0.96}
      ]
    },
    {
      "segment_id": 2,
      "start": 5.80,
      "end": 10.45,
      "text": "Notice how the timestamps accurately align with the speech segments, even when long pauses are removed by Silero VAD.",
      "confidence": 0.94,
      "words": null
    }
  ],
  "chunk_files": [
    "storage/recordings/4b684cb3-078c-4a37-b95a-c5adab3d1f02/chunks/chunk_001.wav",
    "storage/recordings/4b684cb3-078c-4a37-b95a-c5adab3d1f02/chunks/chunk_002.wav"
  ],
  "created_at": "2026-11-02T10:00:00+00:00",
  "error_message": null
}
```

---

### Stream Original Standardized WAV Audio
```bash
curl -X GET "http://localhost:8000/api/v1/recordings/4b684cb3-078c-4a37-b95a-c5adab3d1f02/audio" \
  --output playback.wav
```

---

### Delete Recording & Clean Disk Files
```bash
curl -X DELETE "http://localhost:8000/api/v1/recordings/4b684cb3-078c-4a37-b95a-c5adab3d1f02"
```

---

## Running Automated Tests

Run the full pytest suite:
```bash
pytest -v
```

---

## Docker Deployment

Build and run the container:
```bash
docker build -t speech-pipeline .
docker run -d -p 8000:8000 -v $(pwd)/storage:/app/storage --name speech-pipeline speech-pipeline
```

---

## Performance Tuning Guidance

1. **Sequential vs. Parallel Chunking**:
   - Sequential (`PARALLEL_WORKERS=1`) is enabled by default to prevent GPU VRAM fragmentation and preserve maximum recognition accuracy.
   - On high-end multi-core CPUs or GPUs with `>= 16GB VRAM`, setting `PARALLEL_WORKERS=2` or `4` in `.env` can speed up long audio transcriptions by up to 2.5x.
2. **VAD Settings**:
   - `VAD_THRESHOLD=0.5`: Increase to `0.6` in noisy environments; decrease to `0.4` for quiet whispers.
   - `VAD_SPEECH_PAD_MS=200`: Ensures word initial consonants and trailing fricatives are never clipped.
   - `VAD_OVERLAP_MS=200`: Ensures words falling exactly on the 5-second chunk boundary are preserved.
