"""
Service ASR en streaming avec diarisation légère (numpy uniquement).

Pipeline :
  1. receive_chunk()  → buffer audio
  2. Flush déclenché par timer (1.5s) OU silence (changement de voix)
  3. WhisperASR       → segments texte avec timestamps
  4. LightDiarizer    → MFCC embedding + cosine similarity clustering
  5. on_segment()     → callback vers l'API
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, List, Optional

import numpy as np

from backend.models.meeting import TranscriptSegment

logger = logging.getLogger(__name__)

# ── faster-whisper ────────────────────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    logger.warning("faster-whisper non disponible — mode stub activé")

# ── Configuration ─────────────────────────────────────────────────────────────
SAMPLE_RATE        = 16000
CHUNK_DURATION     = 0.5
ACCUMULATE_SECONDS = 1.5    # flush toutes les 1.5s (vs 3.0s avant)
PARTIAL_INTERVAL   = 1.5
MODEL_SIZE         = "base"

SILENCE_RMS        = 0.004  # seuil RMS en dessous duquel = silence
SILENCE_CHUNKS_MIN = 2      # chunks silence consécutifs → flush anticipé (~1s)
MIN_BUFFER_SILENCE = SAMPLE_RATE * 2 * 0.6  # buffer minimum avant flush silence

SPEAKER_SIMILARITY = 0.92   # seuil cosine similarity spectral (embedding normalisé)
MAX_SPEAKERS       = 20


# ── Diariseur MFCC (numpy only) ───────────────────────────────────────────────
class LightDiarizer:
    """
    Diarisation en ligne par embeddings MFCC + cosine similarity.
    100% numpy, aucune dépendance C++.

    Pour chaque segment Whisper :
      - Extrait le sous-array audio correspondant aux timestamps
      - Calcule un vecteur MFCC moyen (20 coefficients)
      - Compare cosine similarity avec les locuteurs connus
      - Crée un nouvel ID si aucun match au-dessus du seuil
    """

    def __init__(self):
        self._speakers: list[tuple[str, np.ndarray]] = []
        self._counter  = 1

    def reset(self):
        self._speakers.clear()
        self._counter = 1

    def _speaker_embedding(self, audio_np: np.ndarray) -> Optional[np.ndarray]:
        """
        Embedding vocal par profil spectral en bandes de fréquence.
        Bien plus discriminant que MFCC moyen pour distinguer homme/femme
        et locuteurs différents : capture pitch, formants, timbre.
        """
        if len(audio_np) < 400:
            return None

        # Spectre de puissance sur tout le signal (haute résolution fréquentielle)
        N     = max(4096, len(audio_np))
        fft   = np.abs(np.fft.rfft(audio_np, n=N)) ** 2
        freqs = np.fft.rfftfreq(N, d=1.0 / SAMPLE_RATE)

        # 16 bandes centrées sur les zones clés voix humaine
        # (pitch H ~80-180Hz, pitch F ~180-300Hz, formants 300-3500Hz)
        band_limits = [60, 100, 150, 200, 250, 300, 400, 550,
                       750, 1000, 1500, 2000, 2800, 3500, 5000, 8000]
        features = []
        for i in range(len(band_limits) - 1):
            lo, hi = band_limits[i], band_limits[i + 1]
            mask   = (freqs >= lo) & (freqs < hi)
            energy = np.mean(fft[mask]) if mask.any() else 0.0
            features.append(float(energy))

        # ZCR (proxy du pitch : voix grave → peu de ZCR, voix aiguë → beaucoup)
        zcr = float(np.mean(np.abs(np.diff(np.sign(audio_np)))) / 2)
        features.append(zcr)

        # Centroïde spectral (femme > homme en général)
        total = np.sum(fft) + 1e-10
        centroid = float(np.sum(freqs * fft) / total)
        features.append(centroid / (SAMPLE_RATE / 2))  # normalisé [0,1]

        emb = np.array(features)
        norm = np.linalg.norm(emb)
        return emb / norm if norm > 1e-8 else None

    # ── Identification locuteur ────────────────────────────────────────────────
    def identify(self, audio_bytes: bytes,
                 seg_start: float, seg_end: float,
                 chunk_start_time: float) -> str:
        try:
            full = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            # Extraire le sous-array du segment Whisper
            s = max(0, int((seg_start - chunk_start_time) * SAMPLE_RATE))
            e = min(len(full), int((seg_end   - chunk_start_time) * SAMPLE_RATE))
            seg_audio = full[s:e] if e > s else full

            # Compléter si trop court (besoin d'au moins ~0.4s pour MFCC)
            if len(seg_audio) < 640:
                seg_audio = full if len(full) >= 640 else np.pad(full, (0, 640 - len(full)))

            emb = self._speaker_embedding(seg_audio)
            if emb is None:
                return "Intervenant 1"

            if not self._speakers:
                name = f"Intervenant {self._counter}"
                self._speakers.append((name, emb))
                self._counter += 1
                return name

            # Cosine similarity
            norm_emb = emb / (np.linalg.norm(emb) + 1e-8)
            sims = [
                (name, float(np.dot(norm_emb, sp / (np.linalg.norm(sp) + 1e-8))))
                for name, sp in self._speakers
            ]
            best_name, best_sim = max(sims, key=lambda x: x[1])

            if best_sim >= SPEAKER_SIMILARITY:
                # Mise à jour moyenne glissante de l'embedding
                idx = next(i for i, (n, _) in enumerate(self._speakers) if n == best_name)
                self._speakers[idx] = (best_name, 0.85 * self._speakers[idx][1] + 0.15 * emb)
                return best_name

            if len(self._speakers) < MAX_SPEAKERS:
                name = f"Intervenant {self._counter}"
                self._speakers.append((name, emb))
                self._counter += 1
                return name

            return best_name  # plafond atteint → locuteur le plus proche

        except Exception as e:
            logger.debug(f"Diarisation erreur: {e}")
            return "Intervenant 1"


# ── Stub ASR ──────────────────────────────────────────────────────────────────
class StubASR:
    async def transcribe_chunk(self, audio_bytes: bytes, start_time: float) -> List[TranscriptSegment]:
        await asyncio.sleep(0.1)
        duration = len(audio_bytes) / (SAMPLE_RATE * 2)
        return [TranscriptSegment(
            id=str(uuid.uuid4()), start=start_time, end=start_time + duration,
            speaker="Intervenant 1", text=f"[stub] {duration:.1f}s",
            confidence=0.5, is_partial=False,
        )]


# ── Whisper ASR ───────────────────────────────────────────────────────────────
class WhisperASR:
    def __init__(self, model_size: str = MODEL_SIZE):
        logger.info(f"Chargement Whisper '{model_size}' sur cpu...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("Whisper chargé.")

    async def transcribe_chunk(self, audio_bytes: bytes, start_time: float) -> List[TranscriptSegment]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_transcribe, audio_bytes, start_time)

    def _sync_transcribe(self, audio_bytes: bytes, start_time: float) -> List[TranscriptSegment]:
        try:
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            segs, _ = self.model.transcribe(
                audio_np,
                language="fr",
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=250),
            )
            result = []
            for seg in segs:
                if not seg.text.strip():
                    continue
                result.append(TranscriptSegment(
                    id=str(uuid.uuid4()),
                    start=start_time + seg.start,
                    end=start_time + seg.end,
                    speaker="__DIARIZE__",
                    text=seg.text.strip(),
                    confidence=max(0.0, 1.0 + seg.avg_logprob),
                    is_partial=False,
                ))
            return result
        except Exception as e:
            logger.error(f"Erreur transcription: {e}")
            return []


# ── Streaming ASR Manager ─────────────────────────────────────────────────────
class StreamingASRService:
    def __init__(self):
        self._asr      = WhisperASR() if FASTER_WHISPER_AVAILABLE else StubASR()
        self._diarizer = LightDiarizer()

        self._buffer:            bytearray = bytearray()
        self._buffer_start_time: float    = 0.0
        self._elapsed:           float    = 0.0
        self._last_flush_time:   float    = 0.0
        self._last_partial_time: float    = 0.0
        self._silence_chunks:    int      = 0
        self._running:           bool     = False

        self.on_partial: Optional[Callable] = None
        self.on_segment: Optional[Callable] = None

    def start(self):
        self._buffer.clear()
        self._buffer_start_time = 0.0
        self._elapsed           = 0.0
        self._last_flush_time   = time.time()
        self._last_partial_time = time.time()
        self._silence_chunks    = 0
        self._running           = True
        self._diarizer.reset()
        logger.info("StreamingASRService démarré")

    def stop(self):
        self._running = False
        logger.info("StreamingASRService arrêté")

    async def receive_chunk(self, audio_bytes: bytes):
        if not self._running:
            return

        self._buffer.extend(audio_bytes)
        self._elapsed += len(audio_bytes) / (SAMPLE_RATE * 2)
        now = time.time()

        # Détection silence → flush anticipé au changement de locuteur
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        self._silence_chunks = (self._silence_chunks + 1) if rms < SILENCE_RMS else 0

        silence_flush = (
            self._silence_chunks >= SILENCE_CHUNKS_MIN
            and len(self._buffer) >= MIN_BUFFER_SILENCE
        )
        time_flush = (now - self._last_flush_time) >= ACCUMULATE_SECONDS

        if time_flush or silence_flush:
            if silence_flush:
                logger.info("[ASR] Flush anticipé (silence → changement de locuteur ?)")
            self._silence_chunks = 0
            await self._flush()
            self._last_flush_time = now

        if now - self._last_partial_time >= PARTIAL_INTERVAL:
            self._last_partial_time = now
            if self.on_partial and len(self._buffer) > 0:
                await self.on_partial(
                    f"[...transcription en cours ({self._elapsed:.1f}s)]",
                    self._buffer_start_time,
                )

    async def flush_remaining(self):
        if len(self._buffer) > 0:
            await self._flush()

    async def _flush(self):
        buf_len = len(self._buffer)
        logger.info(f"[ASR] _flush — {buf_len/(SAMPLE_RATE*2):.2f}s audio")
        if buf_len < SAMPLE_RATE * 2 * 0.3:
            return

        audio_data  = bytes(self._buffer)
        start_time  = self._buffer_start_time
        self._buffer_start_time = self._elapsed
        self._buffer.clear()

        segments = await self._asr.transcribe_chunk(audio_data, start_time)
        logger.info(f"[ASR] {len(segments)} segment(s)")

        for seg in segments:
            if seg.speaker == "__DIARIZE__":
                seg.speaker = self._diarizer.identify(
                    audio_data, seg.start, seg.end, start_time
                )
            logger.info(f"[ASR] [{seg.speaker}] '{seg.text[:60]}'")
            if self.on_segment and seg.text.strip():
                await self.on_segment(seg)


# ── Factory / Singleton ───────────────────────────────────────────────────────
def create_asr_service() -> StreamingASRService:
    return StreamingASRService()

_asr_service: StreamingASRService | None = None

def get_asr_service() -> StreamingASRService:
    global _asr_service
    if _asr_service is None:
        _asr_service = StreamingASRService()
    return _asr_service
