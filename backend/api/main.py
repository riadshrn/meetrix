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
from fastapi.responses import Response

from backend.models.meeting import (
    CalendarEventRequest, CreateTaskRequest, MeetingReport, MomentType,
    QARequest, QAResponse, StartMeetingRequest,
    StartMeetingResponse, StopMeetingResponse, TranscriptSegment,
)
from backend.services.asr_service import get_asr_service
from backend.services.calendar_service import get_calendar_service, get_tasks_service
from backend.services.db_service import delete_report as db_delete, get_report as db_get, init_db, list_reports as db_list, save_report as db_save
from backend.services.export_service import generate_markdown, generate_pdf
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
    init_db()
    logger.info("🚀 Meeting AI Assistant démarré")
    yield
    await get_llm_service().close()

app = FastAPI(title="Meeting AI Assistant", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_last_report: Optional[MeetingReport] = None

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


@app.post("/flush")
async def flush_asr():
    await get_asr_service().flush_remaining()
    return {"ok": True}


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
    global _last_report
    manager = get_meeting_manager()
    if not manager.state:
        raise HTTPException(404, "Aucune réunion disponible.")
    _inject_demo_segments()
    llm = get_llm_service()
    report = await llm.generate_full_report(manager.state)
    _last_report = report
    db_save(report)
    return {"report": report.model_dump()}


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
    return [r.model_dump() for r in db_list()]


@app.delete("/reports/{meeting_id}")
def delete_report(meeting_id: str):
    global _last_report
    if not db_delete(meeting_id):
        raise HTTPException(404, "Compte-rendu introuvable.")
    if _last_report and _last_report.meeting_id == meeting_id:
        remaining = db_list()
        _last_report = remaining[0] if remaining else None
    return {"deleted": meeting_id}


@app.get("/reports/{meeting_id}/markdown")
def export_markdown(meeting_id: str):
    report = db_get(meeting_id)
    if not report:
        raise HTTPException(404, "Compte-rendu introuvable.")
    md = generate_markdown(report)
    return Response(content=md, media_type="text/markdown",
                    headers={"Content-Disposition": f"attachment; filename=rapport_{meeting_id[:8]}.md"})


@app.get("/reports/{meeting_id}/pdf")
def export_pdf(meeting_id: str):
    report = db_get(meeting_id)
    if not report:
        raise HTTPException(404, "Compte-rendu introuvable.")
    pdf_path = generate_pdf(report)
    if not pdf_path:
        raise HTTPException(503, "reportlab non disponible.")
    return Response(content=pdf_path.read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=rapport_{meeting_id[:8]}.pdf"})


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
    report = _last_report or db_get(req.meeting_id)
    if not report:
        raise HTTPException(404, "Aucun rapport. Appelez /report d'abord.")
    try:
        return get_calendar_service().create_meeting_event(req, report)
    except Exception as e:
        logger.error(f"Erreur Calendar : {e}", exc_info=True)
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
            elif "text" in msg and msg["text"]:
                try:
                    data = json.loads(msg["text"])
                    if data.get("type") == "speaker":
                        asr.set_speaker_override(data.get("name"))
                        logger.info(f"[EXT] Locuteur actif : {data.get('name')}")
                except Exception:
                    pass
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
