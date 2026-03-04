"""
Service de statistiques : temps de parole, mots fréquents, moments clés.
"""
from __future__ import annotations

import re
import uuid
from collections import Counter
from typing import Dict, List, Set

from backend.models.meeting import (
    KeyMoment,
    KeywordStats,
    MeetingState,
    MomentType,
    SpeakerStats,
    TranscriptSegment,
)

# ---------------------------------------------------------------------------
# Stopwords français (liste simplifiée)
# ---------------------------------------------------------------------------

FRENCH_STOPWORDS: Set[str] = {
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "en", "est",
    "au", "aux", "ce", "se", "si", "on", "il", "ils", "elle", "elles",
    "je", "tu", "nous", "vous", "que", "qui", "quoi", "dont", "où",
    "par", "sur", "sous", "dans", "avec", "sans", "pour", "mais", "ou",
    "donc", "or", "ni", "car", "plus", "bien", "très", "aussi", "comme",
    "pas", "ne", "à", "être", "avoir", "faire", "tout", "même", "cette",
    "ces", "mon", "ton", "son", "ma", "ta", "sa", "mes", "tes", "ses",
    "nos", "vos", "leur", "leurs", "ça", "cela", "oui", "non", "alors",
    "après", "avant", "pendant", "quand", "parce", "donc", "ainsi",
    "entre", "jusqu", "lors", "dont", "quel", "quelle", "quels", "quelles",
    "chaque", "aucun", "autre", "autres", "était", "ont", "sont", "sera",
    "être", "fait", "faire", "peu", "peut", "faut",
}

# Mots déclencheurs de moments clés
DECISION_TRIGGERS = {"décidé", "décision", "validé", "approuvé", "confirmé", "accord", "convenu"}
ACTION_TRIGGERS = {"va", "devra", "doit", "responsable", "prend", "chargé", "s'engage", "prévoir", "planifier"}
QUESTION_TRIGGERS = {"?", "comment", "pourquoi", "quand", "est-ce", "avez-vous", "savez-vous"}
RISK_TRIGGERS = {"risque", "problème", "bloquant", "difficulté", "inquiet", "danger", "critique"}


# ---------------------------------------------------------------------------
# Stats service
# ---------------------------------------------------------------------------

class StatsService:
    """Calcule et maintient les statistiques de la réunion."""

    def update_speaker_stats(self, state: MeetingState) -> None:
        """Recalcule les stats de temps de parole à partir des segments."""
        totals: Dict[str, Dict] = {}
        total_speech = 0.0

        for seg in state.segments:
            if seg.is_partial:
                continue
            sp = seg.speaker
            dur = max(0.0, seg.end - seg.start)
            total_speech += dur
            if sp not in totals:
                totals[sp] = {"seconds": 0.0, "words": 0, "segments": 0}
            totals[sp]["seconds"] += dur
            totals[sp]["words"] += len(seg.text.split())
            totals[sp]["segments"] += 1

        state.speakers_stats = {
            sp: SpeakerStats(
                speaker=sp,
                total_seconds=v["seconds"],
                word_count=v["words"],
                segment_count=v["segments"],
                percentage=round(v["seconds"] / total_speech * 100, 1) if total_speech > 0 else 0.0,
            )
            for sp, v in totals.items()
        }

    def update_keywords(self, state: MeetingState, top_n: int = 20) -> None:
        """Extrait mots fréquents et bigrammes (hors stopwords)."""
        all_text = " ".join(
            seg.text for seg in state.segments if not seg.is_partial
        ).lower()

        words = _tokenize(all_text)
        filtered = [w for w in words if w not in FRENCH_STOPWORDS and len(w) > 2]

        # Unigrammes
        unigram_counter = Counter(filtered)

        # Bigrammes
        bigrams = [f"{filtered[i]} {filtered[i+1]}" for i in range(len(filtered) - 1)]
        bigram_counter = Counter(bigrams)

        keywords = []
        for term, count in unigram_counter.most_common(top_n):
            keywords.append(KeywordStats(term=term, count=count, is_bigram=False))
        for term, count in bigram_counter.most_common(10):
            if count >= 2:  # seuil bigrammes
                keywords.append(KeywordStats(term=term, count=count, is_bigram=True))

        # Tri global par fréquence
        state.keywords = sorted(keywords, key=lambda x: x.count, reverse=True)[:top_n + 10]

    def detect_key_moments(self, state: MeetingState) -> None:
        """Détecte décisions, actions, questions, risques dans les segments."""
        existing_ids = {km.segment_id for km in state.key_moments}
        
        for seg in state.segments:
            if seg.is_partial or seg.id in existing_ids:
                continue
            
            text_lower = seg.text.lower()
            moment_type = _classify_moment(text_lower)
            
            if moment_type:
                seg.moment_type = moment_type
                state.key_moments.append(KeyMoment(
                    timestamp=seg.start,
                    segment_id=seg.id,
                    moment_type=moment_type,
                    text=seg.text,
                    speaker=seg.speaker,
                ))

    def full_update(self, state: MeetingState) -> None:
        """Mise à jour complète de toutes les stats."""
        self.update_speaker_stats(state)
        self.update_keywords(state)
        self.detect_key_moments(state)
        if state.segments:
            state.total_duration = max(seg.end for seg in state.segments if not seg.is_partial)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Tokenise le texte en mots alphanumériques."""
    return re.findall(r"\b[a-zàâäéèêëîïôöùûüç]{2,}\b", text.lower())


def _classify_moment(text: str) -> MomentType | None:
    """Classifie un texte dans une catégorie de moment clé."""
    if any(w in text for w in RISK_TRIGGERS):
        return MomentType.RISK
    if any(w in text for w in DECISION_TRIGGERS):
        return MomentType.DECISION
    if any(w in text for w in ACTION_TRIGGERS):
        return MomentType.ACTION
    if any(w in text for w in QUESTION_TRIGGERS):
        return MomentType.QUESTION
    return None


# Singleton
_stats_service: StatsService | None = None

def get_stats_service() -> StatsService:
    global _stats_service
    if _stats_service is None:
        _stats_service = StatsService()
    return _stats_service
