"""
Modèles de données Pydantic pour Meeting AI Assistant.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MomentType(str, Enum):
    DECISION = "decision"
    ACTION = "action"
    QUESTION = "question"
    RISK = "risk"


class WSEventType(str, Enum):
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_SEGMENT = "final_segment"
    STATS_UPDATE = "stats_update"
    LLM_ANSWER = "llm_answer"
    ERROR = "error"
    STATUS = "status"


# ---------------------------------------------------------------------------
# Core transcript models
# ---------------------------------------------------------------------------

class TranscriptSegment(BaseModel):
    """Un segment de transcription avec métadonnées speaker."""
    id: str = Field(..., description="UUID du segment")
    start: float = Field(..., description="Timestamp début en secondes")
    end: float = Field(..., description="Timestamp fin en secondes")
    speaker: str = Field(default="Intervenant inconnu", description="Identifiant du speaker")
    text: str = Field(..., description="Texte transcrit")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_partial: bool = Field(default=False)
    moment_type: Optional[MomentType] = None


class SpeakerStats(BaseModel):
    """Statistiques de temps de parole par speaker."""
    speaker: str
    total_seconds: float = 0.0
    word_count: int = 0
    segment_count: int = 0
    percentage: float = 0.0


class KeywordStats(BaseModel):
    """Fréquence d'un mot ou bigramme."""
    term: str
    count: int
    is_bigram: bool = False


class MoodStats(BaseModel):
    """Statistiques d'émotion (placeholder pour option WOW)."""
    speaker: str
    dominant_emotion: str = "neutre"
    confidence: float = 0.0
    emotions: Dict[str, float] = Field(default_factory=dict)


class KeyMoment(BaseModel):
    """Moment clé détecté dans la réunion."""
    timestamp: float
    segment_id: str
    moment_type: MomentType
    text: str
    speaker: str


class MeetingState(BaseModel):
    """État global de la réunion en cours."""
    meeting_id: str
    title: str = "Réunion sans titre"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    segments: List[TranscriptSegment] = Field(default_factory=list)
    speakers_stats: Dict[str, SpeakerStats] = Field(default_factory=dict)
    keywords: List[KeywordStats] = Field(default_factory=list)
    mood_stats: List[MoodStats] = Field(default_factory=list)
    key_moments: List[KeyMoment] = Field(default_factory=list)
    is_recording: bool = False
    total_duration: float = 0.0

    def full_transcript(self, speaker_mapping: dict | None = None) -> str:
        """Retourne la transcription complète sous forme de texte."""
        mapping = speaker_mapping or {}
        lines = []
        for seg in self.segments:
            if not seg.is_partial:
                ts = f"[{seg.start:.1f}s]"
                name = mapping.get(seg.speaker, seg.speaker)
                lines.append(f"{ts} {name}: {seg.text}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Action items / rapport
# ---------------------------------------------------------------------------

class ActionItem(BaseModel):
    """Tâche extraite de la réunion."""
    id: str = Field(..., description="UUID de la tâche")
    assignee: str = Field(default="Non assigné")
    task: str = Field(..., description="Description de la tâche")
    due_date: Optional[str] = Field(default=None, description="Date limite (ISO ou texte libre)")
    priority: Optional[Priority] = Priority.MEDIUM
    context: Optional[str] = None


class MeetingReport(BaseModel):
    """Compte-rendu structuré généré par le LLM."""
    meeting_id: str
    title: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str = ""
    context: str = ""
    discussed_points: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    open_points: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    participants: List[str] = Field(default_factory=list)
    duration_minutes: float = 0.0
    full_transcript: str = ""


# ---------------------------------------------------------------------------
# WebSocket events
# ---------------------------------------------------------------------------

class WSEvent(BaseModel):
    """Événement envoyé via WebSocket au frontend."""
    type: WSEventType
    data: Any
    timestamp: float = Field(default_factory=lambda: datetime.utcnow().timestamp())


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------

class StartMeetingRequest(BaseModel):
    title: str = "Nouvelle réunion"
    participants: List[str] = Field(default_factory=list)


class StartMeetingResponse(BaseModel):
    meeting_id: str
    message: str
    started_at: datetime


class StopMeetingResponse(BaseModel):
    meeting_id: str
    message: str
    duration_seconds: float


class QARequest(BaseModel):
    question: str
    meeting_id: str


class QAResponse(BaseModel):
    question: str
    answer: str
    meeting_id: str


class CalendarEventRequest(BaseModel):
    meeting_id: str
    next_meeting_title: str = "Prochaine réunion"
    next_meeting_datetime: str  # ISO format
    duration_minutes: int = 60
    attendees: List[str] = Field(default_factory=list)
    timezone: str = "Europe/Paris"


class CreateTaskRequest(BaseModel):
    """Requête de création d'une tâche Google Tasks."""
    task: str
    assignee: str = "Non assigné"
    due_date: Optional[str] = None
    notes: Optional[str] = None
    meeting_title: str = ""
