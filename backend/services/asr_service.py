"""
Service ASR (Automatic Speech Recognition) en streaming.
Utilise faster-whisper pour la transcription quasi temps réel.
Fallback : mode stub si faster-whisper non disponible.
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
from collections import deque
from typing import AsyncIterator, Callable, Deque, List, Optional

import numpy as np

from backend.models.meeting import TranscriptSegment

logger = logging.getLogger(__name__)

# Tentative d'import faster-whisper
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    logger.warning("faster-whisper non disponible — mode stub activé")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000          # Hz
CHUNK_DURATION = 0.5         # secondes par chunk audio entrant
ACCUMULATE_SECONDS = 3.0     # accumulation avant transcription
PARTIAL_INTERVAL = 1.5       # intervalle résultats partiels
MODEL_SIZE = "base"          # tiny | base | small | medium | large-v3


# ---------------------------------------------------------------------------
# Stub ASR (si faster-whisper non installé)
# ---------------------------------------------------------------------------

class StubASR:
    """ASR fictif pour développement/tests sans GPU."""

    async def transcribe_chunk(self, audio_bytes: bytes, start_time: float) -> List[TranscriptSegment]:
        await asyncio.sleep(0.1)  # simule latence
        duration = len(audio_bytes) / (SAMPLE_RATE * 2)  # int16
        text = f"[stub] segment audio de {duration:.1f}s"
        seg = TranscriptSegment(
            id=str(uuid.uuid4()),
            start=start_time,
            end=start_time + duration,
            speaker="Intervenant 1",
            text=text,
            confidence=0.5,
            is_partial=False,
        )
        return [seg]


# ---------------------------------------------------------------------------
# Real ASR avec faster-whisper
# ---------------------------------------------------------------------------

class WhisperASR:
    """Transcription réelle avec faster-whisper (CPU/GPU)."""

    def __init__(self, model_size: str = MODEL_SIZE, device: str = "cpu", compute_type: str = "int8"):
        logger.info(f"Chargement modèle Whisper '{model_size}' sur {device}...")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("Modèle Whisper chargé.")

    async def transcribe_chunk(self, audio_bytes: bytes, start_time: float) -> List[TranscriptSegment]:
        """Transcrit un chunk audio (int16 PCM 16kHz mono)."""
        loop = asyncio.get_event_loop()
        segments = await loop.run_in_executor(None, self._sync_transcribe, audio_bytes, start_time)
        return segments

    def _sync_transcribe(self, audio_bytes: bytes, start_time: float) -> List[TranscriptSegment]:
        try:
            # Conversion bytes → float32 numpy
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            segments_iter, info = self.model.transcribe(
                audio_np,
                language="fr",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
            )

            result = []
            for seg in segments_iter:
                ts = TranscriptSegment(
                    id=str(uuid.uuid4()),
                    start=start_time + seg.start,
                    end=start_time + seg.end,
                    speaker="Intervenant inconnu",  # diarization optionnelle
                    text=seg.text.strip(),
                    confidence=seg.avg_logprob,  # approximation
                    is_partial=False,
                )
                result.append(ts)
            return result
        except Exception as e:
            logger.error(f"Erreur transcription: {e}")
            return []


# ---------------------------------------------------------------------------
# Streaming ASR Manager
# ---------------------------------------------------------------------------

class StreamingASRService:
    """
    Gère l'accumulation de chunks audio et déclenche la transcription.
    
    Flux:
      - receive_chunk(bytes) → accumule dans un buffer
      - Toutes les ACCUMULATE_SECONDS : transcrit + émet final_segment
      - Toutes les PARTIAL_INTERVAL : émet partial_transcript (estimation)
    """

    def __init__(self):
        self._asr = WhisperASR() if FASTER_WHISPER_AVAILABLE else StubASR()
        self._buffer: bytearray = bytearray()
        self._buffer_start_time: float = 0.0
        self._last_partial_time: float = 0.0
        self._last_flush_time: float = 0.0
        self._elapsed: float = 0.0
        self._running: bool = False
        self._speaker_counter: int = 1
        self._speaker_map: dict = {}

        # Callbacks
        self.on_partial: Optional[Callable] = None   # (text: str, start: float)
        self.on_segment: Optional[Callable] = None   # (segment: TranscriptSegment)

    def start(self):
        self._buffer.clear()
        self._buffer_start_time = 0.0
        self._last_partial_time = time.time()
        self._last_flush_time = time.time()
        self._elapsed = 0.0
        self._running = True
        logger.info("StreamingASRService démarré")

    def stop(self):
        self._running = False
        logger.info("StreamingASRService arrêté")

    async def receive_chunk(self, audio_bytes: bytes):
        """Reçoit un chunk audio (bytes PCM int16 16kHz mono)."""
        if not self._running:
            return

        chunk_duration = len(audio_bytes) / (SAMPLE_RATE * 2)
        self._buffer.extend(audio_bytes)
        self._elapsed += chunk_duration
        now = time.time()

        # Résultat partiel (UI responsive)
        if now - self._last_partial_time >= PARTIAL_INTERVAL:
            self._last_partial_time = now
            if self.on_partial and len(self._buffer) > 0:
                await self.on_partial(
                    f"[...transcription en cours ({self._elapsed:.1f}s de audio accumulé)]",
                    self._buffer_start_time,
                )

        # Flush et transcription réelle
        if now - self._last_flush_time >= ACCUMULATE_SECONDS:
            await self._flush()
            self._last_flush_time = now

    async def flush_remaining(self):
        """Vide le buffer restant à la fin de la réunion."""
        if len(self._buffer) > 0:
            await self._flush()

    async def _flush(self):
        """Transcrit le buffer courant et émet les segments."""
        if len(self._buffer) < SAMPLE_RATE * 2 * 0.3:  # ignore < 300ms
            return

        audio_data = bytes(self._buffer)
        start_time = self._buffer_start_time

        # Reset buffer
        self._buffer_start_time = self._elapsed
        self._buffer.clear()

        segments = await self._asr.transcribe_chunk(audio_data, start_time)

        for seg in segments:
            seg.speaker = self._assign_speaker(seg.speaker)
            if self.on_segment and seg.text.strip():
                await self.on_segment(seg)

    def _assign_speaker(self, raw_speaker: str) -> str:
        """Mappe les identifiants speaker vers des noms lisibles."""
        if raw_speaker not in self._speaker_map:
            self._speaker_map[raw_speaker] = f"Intervenant {self._speaker_counter}"
            self._speaker_counter += 1
        return self._speaker_map[raw_speaker]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_asr_service() -> StreamingASRService:
    return StreamingASRService()
