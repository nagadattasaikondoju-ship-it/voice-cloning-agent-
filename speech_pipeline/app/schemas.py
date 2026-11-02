from typing import List, Optional
from pydantic import BaseModel, Field


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float
    probability: Optional[float] = None


class SegmentResponse(BaseModel):
    segment_id: int
    start: float
    end: float
    text: str
    confidence: Optional[float] = None
    words: Optional[List[WordTimestamp]] = None


class RecordingResponse(BaseModel):
    recording_id: str
    status: str
    duration_seconds: Optional[float] = None
    language: Optional[str] = None
    language_probability: Optional[float] = None
    full_transcript: Optional[str] = None
    segments: List[SegmentResponse] = Field(default_factory=list)
    chunk_files: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    error_message: Optional[str] = None


class Base64RecordingRequest(BaseModel):
    audio_base64: str = Field(..., description="Base64 encoded audio string (WAV, WEBM, MP3, etc.)")
    filename: Optional[str] = Field("recording.wav", description="Filename hint for format resolution")
    language: Optional[str] = Field(None, description="Optional ISO language code like 'en', 'es'")


class CreateRecordingResponse(BaseModel):
    recording_id: str
    status: str
    duration_seconds: float
    message: str


class ProcessJobResponse(BaseModel):
    recording_id: str
    status: str
    message: str


class VADRegion(BaseModel):
    region_id: int
    start_s: float
    end_s: float
    duration_s: float
    sample_start: int
    sample_end: int


class VADMetadata(BaseModel):
    sample_rate: int
    total_audio_duration_s: float
    speech_duration_s: float
    speech_percentage: float
    regions: List[VADRegion] = Field(default_factory=list)
