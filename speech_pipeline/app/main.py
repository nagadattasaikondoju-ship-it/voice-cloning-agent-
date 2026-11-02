import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.storage.database import init_db
from app.api.routes import router as api_router

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("speech_pipeline.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler:
    1. Initializes SQLite tables and indexes.
    2. Logs active Whisper and VAD settings.
    """
    logger.info("Initializing Speech Pipeline Application...")
    init_db()
    device, model_name, compute_type = settings.get_whisper_device_and_model()
    logger.info(
        f"ASR Configuration: device='{device}', model='{model_name}', "
        f"compute_type='{compute_type}', parallel_workers={settings.parallel_workers}"
    )
    logger.info(
        f"Silero VAD Configuration: sample_rate={settings.vad_sample_rate}Hz, "
        f"threshold={settings.vad_threshold}, max_chunk={settings.vad_max_speech_duration_s}s"
    )
    yield
    logger.info("Shutting down Speech Pipeline Application gracefully...")


app = FastAPI(
    title="Local-First Speech-to-Text Pipeline",
    description="High-accuracy, local-first speech transcription with Silero VAD chunking and faster-whisper.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router)

# Mount web UI directory
web_dir = Path(__file__).resolve().parent.parent / "web"
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        index_file = web_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "Speech Pipeline API is online. UI index.html not found."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
