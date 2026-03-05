"""
Service ASR en streaming avec diarisation ECAPA-TDNN (speechbrain).

Pipeline :
  1. receive_chunk()  → buffer audio
  2. Flush déclenché par timer (1.5s) OU silence (changement de voix)
  3. WhisperASR       → segments texte avec timestamps
  4. EcapaDiarizer    → embeddings ECAPA-TDNN + cosine similarity clustering
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
ACCUMULATE_SECONDS = 0.8    # flush toutes les 0.8s pour réduire la latence
PARTIAL_INTERVAL   = 0.8
MODEL_SIZE         = "large-v2"

SILENCE_RMS        = 0.004  # seuil RMS en dessous duquel = silence
SILENCE_CHUNKS_MIN = 2      # chunks silence consécutifs → flush anticipé (~1s)
MIN_BUFFER_SILENCE = SAMPLE_RATE * 2 * 0.6  # buffer minimum avant flush silence

SPEAKER_SIMILARITY = 0.50   # seuil cosine similarity ECAPA-TDNN
MAX_SPEAKERS       = 20

# ── Diariseur ECAPA-TDNN (speechbrain) ───────────────────────────────────────
try:
    import torch
    import torchaudio
    import huggingface_hub
    # Patch torchaudio 2.x : list_audio_backends supprimé
    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: []
    # Patch huggingface_hub 1.x : use_auth_token → token
    _orig_hf_download = huggingface_hub.hf_hub_download
    def _patched_hf_download(*args, **kwargs):
        if "use_auth_token" in kwargs:
            kwargs["token"] = kwargs.pop("use_auth_token")
        return _orig_hf_download(*args, **kwargs)
    huggingface_hub.hf_hub_download = _patched_hf_download
    from speechbrain.pretrained import EncoderClassifier
    SPEECHBRAIN_AVAILABLE = True
except ImportError:
    SPEECHBRAIN_AVAILABLE = False
    logger.warning("speechbrain non disponible — fallback numpy")


class EcapaDiarizer:
    """
    Diarisation en ligne par embeddings ECAPA-TDNN (speechbrain).
    Beaucoup plus stable que MFCC pour distinguer 5+ locuteurs.
    """

    def __init__(self):
        self._speakers: list[tuple[str, np.ndarray]] = []
        self._counter  = 1
        self._model    = None
        if SPEECHBRAIN_AVAILABLE:
            try:
                logger.info("Chargement ECAPA-TDNN...")
                self._model = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    run_opts={"device": "cpu"},
                )
                logger.info("ECAPA-TDNN chargé.")
            except Exception as e:
                logger.warning(f"ECAPA-TDNN échec: {e} — fallback numpy")
                self._model = None

    def reset(self):
        self._speakers.clear()
        self._counter = 1

    def _embed(self, audio_np: np.ndarray) -> Optional[np.ndarray]:
        if self._model is not None:
            try:
                # ECAPA attend un tensor float32 [1, T] à 16kHz
                wav = torch.tensor(audio_np, dtype=torch.float32).unsqueeze(0)
                with torch.no_grad():
                    emb = self._model.encode_batch(wav).squeeze().numpy()
                norm = np.linalg.norm(emb)
                return emb / norm if norm > 1e-8 else None
            except Exception as e:
                logger.debug(f"ECAPA embed erreur: {e}")

        # Fallback numpy spectral
        if len(audio_np) < 400:
            return None
        N     = max(4096, len(audio_np))
        fft   = np.abs(np.fft.rfft(audio_np, n=N)) ** 2
        freqs = np.fft.rfftfreq(N, d=1.0 / SAMPLE_RATE)
        band_limits = [60, 100, 150, 200, 250, 300, 400, 550,
                       750, 1000, 1500, 2000, 2800, 3500, 5000, 8000]
        features = []
        for i in range(len(band_limits) - 1):
            lo, hi = band_limits[i], band_limits[i + 1]
            mask   = (freqs >= lo) & (freqs < hi)
            features.append(float(np.mean(fft[mask])) if mask.any() else 0.0)
        zcr = float(np.mean(np.abs(np.diff(np.sign(audio_np)))) / 2)
        features.append(zcr)
        total = np.sum(fft) + 1e-10
        features.append(float(np.sum(freqs * fft) / total) / (SAMPLE_RATE / 2))
        emb = np.array(features)
        norm = np.linalg.norm(emb)
        return emb / norm if norm > 1e-8 else None

    def identify(self, audio_bytes: bytes,
                 seg_start: float, seg_end: float,
                 chunk_start_time: float) -> str:
        try:
            full = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            s = max(0, int((seg_start - chunk_start_time) * SAMPLE_RATE))
            e = min(len(full), int((seg_end - chunk_start_time) * SAMPLE_RATE))
            seg_audio = full[s:e] if e > s else full
            if len(seg_audio) < 1600:
                seg_audio = full if len(full) >= 1600 else np.pad(full, (0, max(0, 1600 - len(full))))

            emb = self._embed(seg_audio)
            if emb is None:
                return "Intervenant 1"

            if not self._speakers:
                name = f"Intervenant {self._counter}"
                self._speakers.append((name, emb))
                self._counter += 1
                return name

            sims = [
                (name, float(np.dot(emb, sp / (np.linalg.norm(sp) + 1e-8))))
                for name, sp in self._speakers
            ]
            best_name, best_sim = max(sims, key=lambda x: x[1])
            logger.info(f"[DIAR] best={best_name} sim={best_sim:.3f} seuil={SPEAKER_SIMILARITY}")

            if best_sim >= SPEAKER_SIMILARITY:
                idx = next(i for i, (n, _) in enumerate(self._speakers) if n == best_name)
                self._speakers[idx] = (best_name, 0.85 * self._speakers[idx][1] + 0.15 * emb)
                return best_name

            if len(self._speakers) < MAX_SPEAKERS:
                name = f"Intervenant {self._counter}"
                self._speakers.append((name, emb))
                self._counter += 1
                return name

            return best_name

        except Exception as e:
            logger.debug(f"Diarisation erreur: {e}")
            return "Intervenant 1"


# ── Filtre hallucinations Whisper ────────────────────────────────────────────
_HALLUCINATION_PATTERNS = [
    "amara.org", "sous-titres réalisés", "sous-titrage", "transcrit par",
    "merci d'avoir regardé", "merci d'avoir visionné", "sous-titres par",
    "traduit par", "abonnez-vous", "n'oubliez pas de liker",
    "musique", "♪", "[musique]", "[music]", "(musique)", "(music)",
]

def _is_hallucination(text: str) -> bool:
    lower = text.lower().strip()
    return any(p in lower for p in _HALLUCINATION_PATTERNS)


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
                beam_size=2,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300, speech_pad_ms=100),
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.0,
                log_prob_threshold=-1.0,
            )
            result = []
            for seg in segs:
                text = seg.text.strip()
                if not text:
                    continue
                # Filtre les hallucinations connues de Whisper
                if _is_hallucination(text):
                    logger.debug(f"[ASR] Hallucination filtrée : {text[:60]}")
                    continue
                result.append(TranscriptSegment(
                    id=str(uuid.uuid4()),
                    start=start_time + seg.start,
                    end=start_time + seg.end,
                    speaker="__DIARIZE__",
                    text=text,
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
        self._diarizer = EcapaDiarizer()

        self._buffer:            bytearray = bytearray()
        self._buffer_start_time: float    = 0.0
        self._elapsed:           float    = 0.0
        self._last_flush_time:   float    = 0.0
        self._last_partial_time: float    = 0.0
        self._silence_chunks:    int      = 0
        self._running:           bool     = False
        self._speaker_override:  Optional[str] = None

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
        self._speaker_override  = None
        self._diarizer.reset()
        logger.info("StreamingASRService démarré")

    def stop(self):
        self._running = False
        logger.info("StreamingASRService arrêté")

    def set_speaker_override(self, name: Optional[str]):
        self._speaker_override = name

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
                if self._speaker_override:
                    seg.speaker = self._speaker_override
                else:
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
