import os
import math
import logging
import threading
from typing import Optional, Tuple, List, Dict, Any
from app.config import settings

logger = logging.getLogger("speech_pipeline.whisper_engine")


class WhisperEngineSingleton:
    """
    Singleton manager for faster-whisper WhisperModel.
    Loads model based on GPU/CPU availability.
    """
    _instance: Optional["WhisperEngineSingleton"] = None
    _lock = threading.Lock()
    _model = None
    _device: str = "cpu"
    _model_name: str = "base"
    _compute_type: str = "int8"

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(WhisperEngineSingleton, cls).__new__(cls)
                cls._instance._init_model()
            return cls._instance

    def _init_model(self):
        """Initializes faster-whisper model."""
        device, model_name, compute_type = settings.get_whisper_device_and_model()
        self._device = device
        self._model_name = model_name
        self._compute_type = compute_type

        logger.info(
            f"Loading faster-whisper: model='{model_name}', "
            f"device='{device}', compute_type='{compute_type}'"
        )

        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                cpu_threads=max(1, os.cpu_count() or 4)
            )
            logger.info("faster-whisper model loaded successfully.")
        except Exception as e:
            logger.warning(
                f"Failed to load faster-whisper with {device}/{compute_type}: {e}. "
                "Attempting CPU fallback with 'base'..."
            )
            try:
                from faster_whisper import WhisperModel
                self._device = "cpu"
                self._model_name = "base"
                self._compute_type = "int8"
                self._model = WhisperModel(
                    "base",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=max(1, os.cpu_count() or 4)
                )
                logger.info("faster-whisper CPU fallback model loaded successfully.")
            except Exception as ex:
                logger.error(f"Failed to initialize faster-whisper model: {ex}")
                self._model = None

    @property
    def model(self):
        return self._model

    @property
    def info(self) -> Dict[str, str]:
        return {
            "device": self._device,
            "model_name": self._model_name,
            "compute_type": self._compute_type
        }


def get_whisper_engine():
    """Returns WhisperEngineSingleton instance."""
    return WhisperEngineSingleton()


def transcribe_chunk_file(
    audio_path: str,
    language: Optional[str] = None,
    word_timestamps: bool = True
) -> Tuple[Optional[str], float, List[Dict[str, Any]]]:
    """
    Transcribes a single chunk WAV file using faster-whisper.
    
    Returns:
    - detected_language: str
    - language_probability: float
    - segments: list of dicts with {start, end, text, confidence, words}
    """
    engine = get_whisper_engine()
    model = engine.model

    if model is None:
        # Fallback stub if faster-whisper model is not available
        logger.warning(f"Whisper model unavailable. Returning empty result for {audio_path}")
        return "en", 1.0, []

    try:
        segments_gen, info = model.transcribe(
            audio_path,
            language=language or settings.whisper_language,
            word_timestamps=word_timestamps,
            beam_size=5,
            vad_filter=False,  # We already run Silero VAD before chunking
            temperature=0.0
        )

        detected_lang = info.language
        lang_prob = float(info.language_probability) if hasattr(info, "language_probability") else 1.0

        segments_list = []
        for seg in segments_gen:
            words = []
            if word_timestamps and hasattr(seg, "words") and seg.words:
                for w in seg.words:
                    words.append({
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": getattr(w, "probability", None)
                    })

            # Calculate confidence proxy from avg_logprob
            avg_logprob = getattr(seg, "avg_logprob", -0.5)
            # exp(avg_logprob) maps to [0, 1]
            confidence = max(0.0, min(1.0, math.exp(avg_logprob))) if avg_logprob is not None else 0.85

            segments_list.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "confidence": confidence,
                "words": words
            })

        return detected_lang, lang_prob, segments_list

    except Exception as e:
        logger.error(f"Error transcribing chunk {audio_path}: {e}")
        raise e
