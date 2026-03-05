"""
Service LLM Mistral.
- Résumé structuré (prompt A)
- Extraction ActionItems JSON (prompt B)  
- Q&A live sur transcript (prompt C)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import List

import httpx

from backend.models.meeting import ActionItem, MeetingReport, MeetingState, Priority

logger = logging.getLogger(__name__)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = "mistral-large-latest"


# ---------------------------------------------------------------------------
# Prompts internes
# ---------------------------------------------------------------------------

PROMPT_A_SUMMARY = """Tu es un assistant expert en analyse de réunions professionnelles.
À partir de la transcription ci-dessous, génère un compte-rendu structuré en français avec exactement ces 4 sections :

**CONTEXTE** : Brève description du contexte et objectif de la réunion (2-3 phrases).
**POINTS DISCUTÉS** : Principaux sujets abordés (3-6 bullet points max, une ligne par point, pas de sous-listes).
**DÉCISIONS** : Uniquement les décisions formelles prises (approbations, choix stratégiques). Une décision complète par bullet point, sans catégories, sans sous-listes, sans nommer des responsables ici.
**POINTS OUVERTS** : Questions non résolues, risques identifiés, sujets à traiter lors de la prochaine réunion (bullet points).

IMPORTANT : Chaque bullet point doit être une phrase complète sur UNE SEULE LIGNE. N'utilise pas de sous-listes ni de catégories en gras suivies de ":".
Sois concis et factuel. N'invente rien qui ne soit pas dans la transcription.

Transcription :
{transcript}
"""

PROMPT_B_ACTION_ITEMS = """Tu es un assistant expert en extraction de tâches depuis des transcriptions de réunions.
Analyse la transcription et extrais TOUTES les tâches, actions et engagements mentionnés.

Réponds UNIQUEMENT avec un JSON valide (aucun texte avant ou après), avec cette structure exacte :
{{
  "action_items": [
    {{
      "assignee": "nom de la personne responsable ou 'Non assigné'",
      "task": "description claire et actionnable de la tâche",
      "due_date": "date limite si mentionnée, sinon null",
      "priority": "high | medium | low",
      "context": "phrase de contexte extraite de la transcription"
    }}
  ]
}}

Transcription :
{transcript}
"""

PROMPT_C_QA = """Tu es un assistant qui répond aux questions basées sur une transcription de réunion.
Réponds en français, de façon précise et concise. Si l'information n'est pas dans la transcription, dis-le clairement.

Transcription de la réunion :
{transcript}

Question : {question}

Réponse :"""


# ---------------------------------------------------------------------------
# Client Mistral
# ---------------------------------------------------------------------------

class MistralClient:
    """Client HTTP simple pour l'API Mistral."""

    def __init__(self):
        self.api_key = os.environ.get("MISTRAL_API_KEY", "")
        if not self.api_key:
            logger.warning("MISTRAL_API_KEY non définie — les appels LLM échoueront")
        self.client = httpx.AsyncClient(timeout=120.0)

    async def _call(self, prompt: str, max_tokens: int = 2000, temperature: float = 0.3) -> str:
        """Appel générique à l'API Mistral."""
        if not self.api_key:
            return "[ERREUR] MISTRAL_API_KEY non configurée."

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            resp = await self.client.post(MISTRAL_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error(f"Mistral API erreur HTTP {e.response.status_code}: {e.response.text}")
            return f"[ERREUR API] {e.response.status_code}"
        except Exception as e:
            logger.error(f"Mistral API erreur: {e}")
            return f"[ERREUR] {str(e)}"

    async def close(self):
        await self.client.aclose()


# ---------------------------------------------------------------------------
# LLM Service
# ---------------------------------------------------------------------------

class LLMService:
    """Service principal LLM utilisant Mistral."""

    def __init__(self):
        self._client = MistralClient()

    async def generate_summary(self, transcript: str) -> str:
        """Prompt A : Résumé structuré de la réunion."""
        if not transcript.strip():
            return "Aucune transcription disponible."
        prompt = PROMPT_A_SUMMARY.format(transcript=transcript[:12000])  # limite contexte
        logger.info("Génération résumé Mistral...")
        return await self._client._call(prompt, max_tokens=1500, temperature=0.2)

    async def extract_action_items(self, transcript: str) -> List[ActionItem]:
        """Prompt B : Extraction des tâches en JSON strict."""
        if not transcript.strip():
            return []
        prompt = PROMPT_B_ACTION_ITEMS.format(transcript=transcript[:12000])
        logger.info("Extraction action items Mistral...")
        raw = await self._client._call(prompt, max_tokens=2000, temperature=0.1)

        try:
            # Nettoyage JSON (parfois le LLM ajoute des balises markdown)
            clean = raw.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
            data = json.loads(clean)
            items = []
            for item in data.get("action_items", []):
                priority_str = item.get("priority", "medium").lower()
                try:
                    priority = Priority(priority_str)
                except ValueError:
                    priority = Priority.MEDIUM
                items.append(ActionItem(
                    id=str(uuid.uuid4()),
                    assignee=item.get("assignee", "Non assigné"),
                    task=item.get("task", ""),
                    due_date=item.get("due_date"),
                    priority=priority,
                    context=item.get("context"),
                ))
            return items
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Erreur parsing action items JSON: {e}\nRaw: {raw[:500]}")
            return []

    async def answer_question(self, question: str, transcript: str) -> str:
        """Prompt C : Q&A sur le transcript (RAG simple)."""
        if not transcript.strip():
            return "Pas de transcription disponible pour répondre à cette question."
        prompt = PROMPT_C_QA.format(
            transcript=transcript[:10000],
            question=question,
        )
        logger.info(f"Q&A Mistral: {question[:80]}")
        return await self._client._call(prompt, max_tokens=800, temperature=0.4)

    async def generate_full_report(self, state: MeetingState, speaker_mapping: dict | None = None) -> MeetingReport:
        """Génère le rapport complet (résumé + action items)."""
        mapping = speaker_mapping or {}
        transcript = state.full_transcript(speaker_mapping=mapping)

        # Appels parallèles
        import asyncio
        summary_task = self.generate_summary(transcript)
        actions_task = self.extract_action_items(transcript)
        summary, action_items = await asyncio.gather(summary_task, actions_task)

        # Parse les sections du résumé
        discussed_points, decisions, open_points, context_text = _parse_summary_sections(summary)

        duration = 0.0
        if state.ended_at:
            duration = (state.ended_at - state.started_at).total_seconds() / 60

        # Appliquer le mapping aux noms de participants
        raw_participants = list(state.speakers_stats.keys())
        participants = [mapping.get(p, p) for p in raw_participants]

        return MeetingReport(
            meeting_id=state.meeting_id,
            title=state.title,
            summary=summary,
            context=context_text,
            discussed_points=discussed_points,
            decisions=decisions,
            open_points=open_points,
            risks=[],
            action_items=action_items,
            participants=participants,
            duration_minutes=duration,
            full_transcript=transcript,
        )

    async def close(self):
        await self._client.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_md(text: str) -> str:
    """Supprime les marqueurs markdown bold et nettoie."""
    import re
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text).strip()


def _parse_summary_sections(summary: str):
    """Extrait les 4 sections du résumé structuré."""
    import re
    sections = {"CONTEXTE": "", "POINTS DISCUTÉS": [], "DÉCISIONS": [], "POINTS OUVERTS": []}
    current = None

    def _is_bullet(s):
        """Détecte un vrai bullet point (pas un titre en gras)."""
        return s.startswith(("-", "•", "·")) or s.startswith("* ")

    for line in summary.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if "CONTEXTE" in upper and not _is_bullet(stripped):
            current = "CONTEXTE"
        elif ("POINTS DISCUTÉS" in upper or "POINTS DISCUTES" in upper) and not _is_bullet(stripped):
            current = "POINTS DISCUTÉS"
        elif ("DÉCISIONS" in upper or "DECISIONS" in upper) and not _is_bullet(stripped):
            current = "DÉCISIONS"
        elif "POINTS OUVERTS" in upper and not _is_bullet(stripped):
            current = "POINTS OUVERTS"
        elif current:
            if current == "CONTEXTE":
                sections[current] += " " + stripped
            elif isinstance(sections[current], list):
                # Extraire le texte du bullet
                if stripped.startswith(("-", "•", "·")):
                    item = stripped.lstrip("-•·· ").strip()
                elif stripped.startswith("* "):
                    item = stripped[2:].strip()
                else:
                    item = stripped
                # Supprimer les marqueurs **...**
                item = _clean_md(item)
                # Ignorer les lignes qui sont juste "Label :" (headers sans contenu)
                if re.match(r'^[^:]{1,40}:\s*$', item):
                    continue
                if item:
                    sections[current].append(item)

    return (
        sections["POINTS DISCUTÉS"],
        sections["DÉCISIONS"],
        sections["POINTS OUVERTS"],
        _clean_md(sections["CONTEXTE"]),
    )


# Singleton
_llm_service: LLMService | None = None

def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
