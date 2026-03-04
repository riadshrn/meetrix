"""
MeetingManager : orchestrateur central de l'état de la réunion.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from backend.models.meeting import MeetingState, TranscriptSegment
from backend.services.asr_service import StreamingASRService, create_asr_service
from backend.services.stats_service import StatsService, get_stats_service

logger = logging.getLogger(__name__)


class MeetingManager:
    """Gère le cycle de vie d'une réunion et coordonne ASR + stats."""

    def __init__(self):
        self.state: Optional[MeetingState] = None
        self._asr: StreamingASRService = create_asr_service()
        self._stats: StatsService = get_stats_service()

        # Callbacks vers le WebSocket handler
        self.on_partial_transcript = None   # async (text, start)
        self.on_final_segment = None        # async (segment)
        self.on_stats_update = None         # async (stats_dict)

        # Wiring ASR → callbacks
        self._asr.on_partial = self._handle_partial
        self._asr.on_segment = self._handle_segment

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_meeting(self, title: str = "Nouvelle réunion", participants: list = None) -> MeetingState:
        meeting_id = str(uuid.uuid4())
        self.state = MeetingState(
            meeting_id=meeting_id,
            title=title,
            started_at=datetime.utcnow(),
            is_recording=True,
        )
        self._asr.start()
        logger.info(f"Réunion démarrée: {meeting_id} — '{title}'")
        return self.state

    async def stop_meeting(self) -> Optional[MeetingState]:
        if not self.state:
            return None
        self.state.is_recording = False
        self._asr.stop()
        await self._asr.flush_remaining()
        self.state.ended_at = datetime.utcnow()
        self._stats.full_update(self.state)
        logger.info(f"Réunion arrêtée: {self.state.meeting_id}")
        return self.state

    def is_recording(self) -> bool:
        return self.state is not None and self.state.is_recording

    # ------------------------------------------------------------------
    # Audio input
    # ------------------------------------------------------------------

    async def process_audio_chunk(self, audio_bytes: bytes):
        """Point d'entrée pour les chunks audio depuis WebSocket."""
        if not self.is_recording():
            return
        await self._asr.receive_chunk(audio_bytes)

    # ------------------------------------------------------------------
    # Internal ASR callbacks
    # ------------------------------------------------------------------

    async def _handle_partial(self, text: str, start: float):
        if self.on_partial_transcript:
            await self.on_partial_transcript(text, start)

    async def _handle_segment(self, segment: TranscriptSegment):
        if not self.state:
            return

        # Ajout au state
        self.state.segments.append(segment)

        # Mise à jour stats légère (speaker seulement)
        self._stats.update_speaker_stats(self.state)
        self._stats.detect_key_moments(self.state)

        if self.on_final_segment:
            await self.on_final_segment(segment)

        if self.on_stats_update:
            stats = self._build_stats_payload()
            await self.on_stats_update(stats)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_stats_payload(self) -> dict:
        """Construit le payload stats pour le frontend."""
        if not self.state:
            return {}
        return {
            "speakers": {
                sp: {
                    "total_seconds": s.total_seconds,
                    "word_count": s.word_count,
                    "percentage": s.percentage,
                }
                for sp, s in self.state.speakers_stats.items()
            },
            "total_duration": self.state.total_duration,
            "segment_count": len([s for s in self.state.segments if not s.is_partial]),
            "key_moments_count": len(self.state.key_moments),
        }

    def get_state_dict(self) -> dict:
        """Sérialise l'état courant pour l'API REST."""
        if not self.state:
            return {}
        return self.state.model_dump()


# Singleton global
_manager: MeetingManager | None = None

def get_meeting_manager() -> MeetingManager:
    global _manager
    if _manager is None:
        _manager = MeetingManager()
    return _manager
