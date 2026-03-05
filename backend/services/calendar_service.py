"""
Service Google Calendar — OAuth 2.0.
Crée un event "Prochaine réunion" avec invités, lien Meet et description.

SETUP :
1. Créer un projet Google Cloud Console
2. Activer Google Calendar API
3. Créer credentials OAuth 2.0 (Desktop app)
4. Télécharger client_secret.json → racine du projet
5. Premier lancement : flow OAuth dans le navigateur → token.json créé
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from backend.models.meeting import CalendarEventRequest, MeetingReport

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]
CREDENTIALS_FILE = Path("client_secret.json")
TOKEN_FILE = Path("token.json")


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _get_credentials():
    """Charge ou génère les credentials OAuth."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise RuntimeError(
            "Dépendances Google manquantes. "
            "Installer: pip install google-api-python-client google-auth-oauthlib"
        )

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        # Vérifier que les scopes du token correspondent aux scopes requis
        if creds and creds.scopes and not set(SCOPES).issubset(set(creds.scopes)):
            logger.warning("Scopes token.json insuffisants — suppression pour re-auth")
            TOKEN_FILE.unlink()
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Fichier {CREDENTIALS_FILE} introuvable. "
                    "Téléchargez-le depuis Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# Calendar service
# ---------------------------------------------------------------------------

class CalendarService:
    """Crée des événements Google Calendar."""

    def create_meeting_event(self, req: CalendarEventRequest, report: MeetingReport) -> dict:
        """
        Crée l'événement 'Prochaine réunion' avec :
        - Lien Google Meet automatique
        - Description = décisions + tâches du rapport
        - Invitations aux participants
        """
        try:
            from googleapiclient.discovery import build
        except ImportError:
            return self._stub_response(req)

        creds = _get_credentials()
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        description = _build_event_description(report)

        event = {
            "summary": req.next_meeting_title,
            "description": description,
            "start": {
                "dateTime": req.next_meeting_datetime,
                "timeZone": req.timezone,
            },
            "end": {
                "dateTime": _add_minutes(req.next_meeting_datetime, req.duration_minutes),
                "timeZone": req.timezone,
            },
            "attendees": [{"email": email} for email in req.attendees],
            "conferenceData": {
                "createRequest": {
                    "requestId": f"meeting-{req.meeting_id[:8]}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 15},
                ],
            },
        }

        created = service.events().insert(
            calendarId="primary",
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()

        meet_link = (
            created.get("conferenceData", {})
            .get("entryPoints", [{}])[0]
            .get("uri", "")
        )

        logger.info(f"Événement créé: {created.get('htmlLink')}")
        return {
            "event_id": created.get("id"),
            "html_link": created.get("htmlLink"),
            "meet_link": meet_link,
            "summary": created.get("summary"),
            "start": req.next_meeting_datetime,
        }

    def _stub_response(self, req: CalendarEventRequest) -> dict:
        """Réponse stub si google-api-python-client non installé."""
        logger.warning("Google Calendar API non disponible — réponse stub")
        return {
            "event_id": "stub-event-id",
            "html_link": "https://calendar.google.com (stub)",
            "meet_link": "https://meet.google.com/xxx-yyyy-zzz (stub)",
            "summary": req.next_meeting_title,
            "start": req.next_meeting_datetime,
            "note": "Installer google-api-python-client pour activer cette fonctionnalité",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_event_description(report: MeetingReport) -> str:
    """Construit la description de l'événement Calendar."""
    parts = [f"📋 Suite de la réunion : {report.title}\n"]

    if report.decisions:
        parts.append("✅ DÉCISIONS PRISES :")
        for d in report.decisions[:10]:
            parts.append(f"  • {d}")
        parts.append("")

    if report.action_items:
        parts.append("📌 TÂCHES EN COURS :")
        for item in report.action_items[:15]:
            due = f" (échéance: {item.due_date})" if item.due_date else ""
            parts.append(f"  • [{item.assignee}] {item.task}{due}")
        parts.append("")

    if report.open_points:
        parts.append("❓ POINTS OUVERTS À TRAITER :")
        for p in report.open_points[:5]:
            parts.append(f"  • {p}")

    return "\n".join(parts)


def _add_minutes(iso_datetime: str, minutes: int) -> str:
    """Ajoute N minutes à une datetime ISO 8601."""
    from datetime import datetime, timedelta
    dt = datetime.fromisoformat(iso_datetime)
    return (dt + timedelta(minutes=minutes)).isoformat()


# Singleton
_calendar_service: CalendarService | None = None

def get_calendar_service() -> CalendarService:
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService()
    return _calendar_service


# ---------------------------------------------------------------------------
# Google Tasks Service
# ---------------------------------------------------------------------------

class GoogleTasksService:
    """Crée des tâches dans Google Tasks."""

    def create_task(self, task: str, assignee: str = "", due_date: str = None, notes: str = None) -> dict:
        """Crée une tâche dans la liste 'My Tasks' de l'utilisateur connecté."""
        try:
            from googleapiclient.discovery import build
        except ImportError:
            return {"error": "google-api-python-client non installé", "stub": True}

        try:
            creds = _get_credentials()
            service = build("tasks", "v1", credentials=creds, cache_discovery=False)

            body = {"title": f"[{assignee}] {task}" if assignee and assignee != "Non assigné" else task}
            if notes:
                body["notes"] = notes
            if due_date:
                # Google Tasks attend RFC 3339 (ex: 2024-12-31T00:00:00.000Z)
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                    body["due"] = dt.strftime("%Y-%m-%dT00:00:00.000Z")
                except Exception:
                    pass

            task_result = service.tasks().insert(tasklist="@default", body=body).execute()
            logger.info(f"Tâche Google Tasks créée: {task_result.get('title')}")
            return {
                "task_id": task_result.get("id"),
                "title": task_result.get("title"),
                "status": task_result.get("status"),
                "link": task_result.get("selfLink"),
            }
        except Exception as e:
            logger.error(f"Erreur création tâche Google Tasks: {e}")
            raise


_tasks_service: GoogleTasksService | None = None

def get_tasks_service() -> GoogleTasksService:
    global _tasks_service
    if _tasks_service is None:
        _tasks_service = GoogleTasksService()
    return _tasks_service
