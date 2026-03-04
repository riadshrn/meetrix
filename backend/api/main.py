"""
Backend FastAPI — Meeting AI Assistant
Routes:
  POST /start          Démarre l'enregistrement
  POST /stop           Arrête et finalise
  POST /report         Génère le rapport LLM
  POST /qa             Q&A live sur la transcription
  GET  /state          État courant de la réunion
  POST /calendar       Crée l'événement Google Calendar
  WS   /ws/audio       WebSocket flux audio
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.models.meeting import (
    ActionItem,
    CalendarEventRequest,
    MeetingReport,
    QARequest,
    QAResponse,
    StartMeetingRequest,
    StartMeetingResponse,
    StopMeetingResponse,
    WSEvent,
    WSEventType,
)
from backend.services.calendar_service import get_calendar_service
from backend.services.export_service import export_report
from backend.services.llm_service import get_llm_service
from backend.services.meeting_manager import get_meeting_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Meeting AI Assistant backend démarré")
    yield
    # Cleanup
    llm = get_llm_service()
    await llm.close()
    logger.info("Backend arrêté proprement")


app = FastAPI(
    title="Meeting AI Assistant API",
    description="Backend temps réel pour transcription, stats et analyse de réunions",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache du rapport le plus récent (en mémoire)
_last_report: Optional[MeetingReport] = None


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/start", response_model=StartMeetingResponse)
async def start_meeting(req: StartMeetingRequest):
    manager = get_meeting_manager()
    if manager.is_recording():
        raise HTTPException(status_code=409, detail="Une réunion est déjà en cours.")
    state = manager.start_meeting(title=req.title, participants=req.participants)
    return StartMeetingResponse(
        meeting_id=state.meeting_id,
        message=f"Réunion '{req.title}' démarrée",
        started_at=state.started_at,
    )


@app.post("/stop", response_model=StopMeetingResponse)
async def stop_meeting():
    manager = get_meeting_manager()
    if not manager.is_recording():
        raise HTTPException(status_code=409, detail="Aucune réunion en cours.")
    state = await manager.stop_meeting()
    duration = (state.ended_at - state.started_at).total_seconds()
    return StopMeetingResponse(
        meeting_id=state.meeting_id,
        message="Réunion arrêtée",
        duration_seconds=duration,
    )


@app.post("/report")
async def generate_report():
    global _last_report
    manager = get_meeting_manager()
    if not manager.state:
        raise HTTPException(status_code=404, detail="Aucune réunion disponible.")
    
    llm = get_llm_service()
    report = await llm.generate_full_report(manager.state)
    _last_report = report

    # Export
    paths = export_report(report)

    return {
        "report": report.model_dump(),
        "exports": paths,
    }


@app.post("/qa", response_model=QAResponse)
async def question_answer(req: QARequest):
    manager = get_meeting_manager()
    if not manager.state:
        raise HTTPException(status_code=404, detail="Aucune réunion disponible.")
    
    transcript = manager.state.full_transcript()
    llm = get_llm_service()
    answer = await llm.answer_question(req.question, transcript)
    
    return QAResponse(
        question=req.question,
        answer=answer,
        meeting_id=req.meeting_id,
    )


@app.get("/state")
async def get_state():
    manager = get_meeting_manager()
    if not manager.state:
        return {"state": None}
    return {"state": manager.get_state_dict()}


@app.post("/calendar")
async def create_calendar_event(req: CalendarEventRequest):
    global _last_report
    if not _last_report:
        raise HTTPException(status_code=404, detail="Aucun rapport généré. Appelez /report d'abord.")
    
    cal = get_calendar_service()
    try:
        result = cal.create_meeting_event(req, _last_report)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report/last")
async def get_last_report():
    if not _last_report:
        raise HTTPException(status_code=404, detail="Aucun rapport disponible.")
    return _last_report.model_dump()


# ---------------------------------------------------------------------------
# WebSocket /ws/audio
# ---------------------------------------------------------------------------

@app.websocket("/ws/audio")
async def websocket_audio(ws: WebSocket):
    """
    WebSocket pour le streaming audio.
    
    Protocole entrée (client → serveur) :
      - bytes bruts : chunk audio PCM int16 16kHz mono
      - JSON string : {"type": "command", "cmd": "ping"|"status"}
    
    Protocole sortie (serveur → client) :
      - JSON : WSEvent {type, data, timestamp}
    """
    await ws.accept()
    manager = get_meeting_manager()

    # Wiring des callbacks vers ce WebSocket
    async def send_event(event_type: WSEventType, data):
        try:
            event = WSEvent(type=event_type, data=data)
            await ws.send_text(event.model_dump_json())
        except Exception:
            pass  # client déconnecté

    async def on_partial(text: str, start: float):
        await send_event(WSEventType.PARTIAL_TRANSCRIPT, {
            "text": text,
            "start": start,
        })

    async def on_segment(segment):
        await send_event(WSEventType.FINAL_SEGMENT, segment.model_dump())

    async def on_stats(stats: dict):
        await send_event(WSEventType.STATS_UPDATE, stats)

    manager.on_partial_transcript = on_partial
    manager.on_final_segment = on_segment
    manager.on_stats_update = on_stats

    await send_event(WSEventType.STATUS, {"message": "WebSocket connecté"})
    logger.info("Client WebSocket connecté")

    try:
        while True:
            message = await ws.receive()
            
            if "bytes" in message and message["bytes"]:
                # Chunk audio brut
                await manager.process_audio_chunk(message["bytes"])

            elif "text" in message and message["text"]:
                # Commandes JSON ou base64
                try:
                    payload = json.loads(message["text"])
                    
                    if isinstance(payload, dict):
                        msg_type = payload.get("type", "")
                        
                        if msg_type == "audio_base64":
                            # Audio encodé en base64
                            audio_bytes = base64.b64decode(payload["data"])
                            await manager.process_audio_chunk(audio_bytes)
                        
                        elif msg_type == "command":
                            cmd = payload.get("cmd", "")
                            if cmd == "ping":
                                await send_event(WSEventType.STATUS, {"message": "pong"})
                            elif cmd == "status":
                                await send_event(WSEventType.STATUS, {
                                    "is_recording": manager.is_recording(),
                                    "segment_count": len(manager.state.segments) if manager.state else 0,
                                })
                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        logger.info("Client WebSocket déconnecté")
    except Exception as e:
        logger.error(f"Erreur WebSocket: {e}")
        await send_event(WSEventType.ERROR, {"message": str(e)})
    finally:
        manager.on_partial_transcript = None
        manager.on_final_segment = None
        manager.on_stats_update = None
