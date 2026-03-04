from __future__ import annotations

import json
import logging
import os
import time
import uuid

from dotenv import load_dotenv
load_dotenv()
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.models.meeting import (
    CalendarEventRequest, CreateTaskRequest, MeetingReport, MomentType,
    QARequest, QAResponse, StartMeetingRequest,
    StartMeetingResponse, StopMeetingResponse, TranscriptSegment,
)
from backend.services.asr_service import get_asr_service
from backend.services.calendar_service import get_calendar_service, get_tasks_service
from backend.services.export_service import export_report
from backend.services.llm_service import get_llm_service
from backend.services.meeting_manager import get_meeting_manager
from backend.services.stats_service import get_stats_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulation data
# ---------------------------------------------------------------------------
DEMO_SEGMENTS = [
    ("Intervenant 1", "Bonjour à tous, commençons la réunion du jour.", None),
    ("Intervenant 2", "J'ai préparé les slides sur le projet Alpha pour ce trimestre.", None),
    ("Intervenant 1", "Décision : on valide le budget de 50 000 euros pour le Q2.", MomentType.DECISION),
    ("Intervenant 3", "Pierre doit envoyer le rapport d'ici vendredi prochain.", MomentType.ACTION),
    ("Intervenant 2", "Est-ce qu'on a bien identifié tous les risques techniques ?", MomentType.QUESTION),
    ("Intervenant 1", "Il y a un risque critique sur l'intégration de l'API externe.", MomentType.RISK),
    ("Intervenant 3", "Je prends en charge la migration de la base de données.", MomentType.ACTION),
    ("Intervenant 2", "On se retrouve la semaine prochaine pour le point d'avancement.", None),
    ("Intervenant 1", "Décision finale : lancement en mode agile, sprints de 2 semaines.", MomentType.DECISION),
    ("Intervenant 3", "Marie doit contacter les parties prenantes avant jeudi.", MomentType.ACTION),
]

def _inject_demo_segments():
    """
    Appelé à chaque GET /state pendant l'enregistrement.
    Injecte un nouveau segment toutes les 3 secondes (basé sur le temps réel écoulé).
    """
    manager = get_meeting_manager()
    if not manager.state or not manager.state.is_recording:
        return

    state = manager.state
    elapsed = (datetime.utcnow() - state.started_at).total_seconds()
    # Combien de segments on devrait avoir à ce stade (1 toutes les 3s)
    expected = min(int(elapsed / 3), len(DEMO_SEGMENTS))
    current = len([s for s in state.segments if not s.is_partial])

    if expected > current:
        for i in range(current, expected):
            speaker, text, moment_type = DEMO_SEGMENTS[i]
            seg = TranscriptSegment(
                id=str(uuid.uuid4()),
                start=float(i * 5),
                end=float(i * 5 + 4),
                speaker=speaker,
                text=text,
                confidence=0.95,
                is_partial=False,
                moment_type=moment_type,
            )
            state.segments.append(seg)
            logger.info(f"[DEMO] +segment {i+1}/{len(DEMO_SEGMENTS)}: {speaker}: {text[:40]}")

        get_stats_service().full_update(state)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Meeting AI Assistant démarré")
    yield
    await get_llm_service().close()

app = FastAPI(title="Meeting AI Assistant", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_last_report: Optional[MeetingReport] = None
_reports_history: List[MeetingReport] = []

HISTORY_FILE = Path("exports/reports_history.json")

def _load_history():
    global _reports_history
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            _reports_history = [MeetingReport(**r) for r in data]
            logger.info(f"Historique chargé: {len(_reports_history)} compte(s)-rendu(s)")
        except Exception as e:
            logger.warning(f"Impossible de charger l'historique: {e}")

def _save_history():
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps([r.model_dump(mode="json") for r in _reports_history], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder l'historique: {e}")

_load_history()

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/start", response_model=StartMeetingResponse)
def start_meeting(req: StartMeetingRequest):
    manager = get_meeting_manager()
    if manager.is_recording():
        raise HTTPException(409, "Une réunion est déjà en cours.")
    state = manager.start_meeting(title=req.title, participants=req.participants)
    logger.info(f"Réunion démarrée: {state.meeting_id}")
    return StartMeetingResponse(
        meeting_id=state.meeting_id,
        message=f"Réunion '{req.title}' démarrée",
        started_at=state.started_at,
    )


@app.post("/stop", response_model=StopMeetingResponse)
async def stop_meeting():
    manager = get_meeting_manager()
    if not manager.is_recording():
        raise HTTPException(409, "Aucune réunion en cours.")
    get_asr_service().stop()  # arrêt explicite de l'ASR
    state = await manager.stop_meeting()
    duration = (state.ended_at - state.started_at).total_seconds()
    return StopMeetingResponse(
        meeting_id=state.meeting_id,
        message="Réunion arrêtée",
        duration_seconds=duration,
    )


@app.get("/state")
def get_state():
    manager = get_meeting_manager()
    if not manager.state:
        return {"state": None}
    return {"state": manager.get_state_dict()}


@app.post("/report")
async def generate_report():
    global _last_report, _reports_history
    manager = get_meeting_manager()
    if not manager.state:
        raise HTTPException(404, "Aucune réunion disponible.")
    _inject_demo_segments()
    llm = get_llm_service()
    report = await llm.generate_full_report(manager.state)
    _last_report = report
    _reports_history.append(report)
    _save_history()
    paths = export_report(report)
    return {"report": report.model_dump(), "exports": paths}


@app.post("/qa", response_model=QAResponse)
async def question_answer(req: QARequest):
    manager = get_meeting_manager()
    if not manager.state:
        raise HTTPException(404, "Aucune réunion disponible.")
    transcript = manager.state.full_transcript()
    answer = await get_llm_service().answer_question(req.question, transcript)
    return QAResponse(question=req.question, answer=answer, meeting_id=req.meeting_id)


@app.post("/reset")
def reset_meeting():
    global _last_report
    manager = get_meeting_manager()
    manager.state = None
    get_asr_service().stop()
    _last_report = None
    return {"message": "Réunion réinitialisée"}


@app.get("/report/last")
def get_last_report():
    if not _last_report:
        raise HTTPException(404, "Aucun rapport disponible.")
    return _last_report.model_dump()


@app.get("/reports")
def list_reports():
    return [r.model_dump() for r in reversed(_reports_history)]


@app.delete("/reports/{meeting_id}")
def delete_report(meeting_id: str):
    global _reports_history, _last_report
    original_len = len(_reports_history)
    _reports_history = [r for r in _reports_history if r.meeting_id != meeting_id]
    if len(_reports_history) == original_len:
        raise HTTPException(404, "Compte-rendu introuvable.")
    if _last_report and _last_report.meeting_id == meeting_id:
        _last_report = _reports_history[-1] if _reports_history else None
    _save_history()
    return {"deleted": meeting_id}


@app.post("/tasks/create")
def create_google_task(req: CreateTaskRequest):
    try:
        return get_tasks_service().create_task(
            task=req.task,
            assignee=req.assignee,
            due_date=req.due_date,
            notes=req.notes or (f"Réunion : {req.meeting_title}" if req.meeting_title else None),
        )
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/calendar")
def create_calendar_event(req: CalendarEventRequest):
    if not _last_report:
        raise HTTPException(404, "Aucun rapport. Appelez /report d'abord.")
    try:
        return get_calendar_service().create_meeting_event(req, _last_report)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.websocket("/ws/audio")
async def websocket_audio(ws: WebSocket):
    await ws.accept()
    await ws.send_text('{"type":"status","data":{"message":"connecté"}}')

    manager = get_meeting_manager()
    asr = get_asr_service()

    async def on_segment(seg: TranscriptSegment):
        if manager.state:
            manager.state.segments.append(seg)
            get_stats_service().full_update(manager.state)
        try:
            await ws.send_text(json.dumps({"type": "final_segment", "data": seg.model_dump()}))
        except Exception:
            pass

    async def on_partial(text: str, start: float):
        try:
            await ws.send_text(json.dumps({"type": "partial_transcript", "data": {"text": text, "start": start}}))
        except Exception:
            pass

    asr.on_segment = on_segment
    asr.on_partial = on_partial
    if not asr._running:
        asr.start()
        logger.info("WebSocket audio connecté — ASR démarré")
    else:
        logger.info("WebSocket audio reconnecté — ASR repris (timestamps préservés)")

    try:
        while True:
            msg = await ws.receive()
            if "bytes" in msg and msg["bytes"]:
                logger.debug(f"Chunk reçu: {len(msg['bytes'])} bytes, recording={manager.is_recording()}")
                await asr.receive_chunk(msg["bytes"])
    except (WebSocketDisconnect, RuntimeError):
        logger.info("WebSocket audio déconnecté — ASR maintenu actif")
        # Ne pas arrêter l'ASR : le frontend va se reconnecter


# ---------------------------------------------------------------------------
# Endpoint debug : injection manuelle d'un segment de démo
# ---------------------------------------------------------------------------
@app.post("/demo/inject")
def inject_demo_segment():
    """Injecte le prochain segment de démo. Appelé par le frontend."""
    manager = get_meeting_manager()
    if not manager.state or not manager.state.is_recording:
        raise HTTPException(400, "Pas de réunion en cours.")
    
    state = manager.state
    current = len([s for s in state.segments if not s.is_partial])
    
    if current >= len(DEMO_SEGMENTS):
        return {"done": True, "total": current}
    
    speaker, text, moment_type = DEMO_SEGMENTS[current]
    seg = TranscriptSegment(
        id=str(uuid.uuid4()),
        start=float(current * 5),
        end=float(current * 5 + 4),
        speaker=speaker,
        text=text,
        confidence=0.95,
        is_partial=False,
        moment_type=moment_type,
    )
    state.segments.append(seg)
    get_stats_service().full_update(state)
    logger.info(f"[DEMO/inject] segment {current+1}: {speaker}: {text[:40]}")
    return {"done": False, "total": current + 1, "segment": seg.model_dump()}
