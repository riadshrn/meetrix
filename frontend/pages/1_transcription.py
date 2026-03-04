import os
import requests
import streamlit as st
import time

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

def init_state():
    defaults = {
        "is_recording": False,
        "segments": [],
        "stats": {},
        "meeting_title": "Ma réunion",
        "error_msg": None,
        "last_segment_count": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

def api_start(title):
    try:
        r = requests.post(f"{BACKEND}/start", json={"title": title}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.session_state["error_msg"] = f"Erreur démarrage: {e}"
        return None

def api_stop():
    try:
        r = requests.post(f"{BACKEND}/stop", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.session_state["error_msg"] = f"Erreur arrêt: {e}"
        return None

def fetch_state():
    """Récupère l'état complet depuis le backend."""
    try:
        r = requests.get(f"{BACKEND}/state", timeout=3)
        r.raise_for_status()
        return r.json().get("state") or {}
    except Exception:
        return {}

# ---- UI ----
st.title("🎙️ Transcription Live")

with st.sidebar:
    st.subheader("⚙️ Configuration")
    st.text_input("Backend URL", value=BACKEND, disabled=True)
    meeting_title = st.text_input("Titre de la réunion", value=st.session_state["meeting_title"])
    st.session_state["meeting_title"] = meeting_title
    st.markdown("---")
    st.info("🤖 **Mode simulation actif**\n\nSegments fictifs générés automatiquement côté backend.")

# Boutons
col_status, col_btn = st.columns([3, 1])
with col_status:
    if st.session_state["is_recording"]:
        st.markdown("🔴 **ENREGISTREMENT EN COURS**")
    else:
        st.markdown("⚫ **EN ATTENTE**")

with col_btn:
    if not st.session_state["is_recording"]:
        if st.button("▶️ Démarrer", type="primary", use_container_width=True):
            result = api_start(st.session_state["meeting_title"])
            if result:
                st.session_state["is_recording"] = True
                st.session_state["segments"] = []
                st.session_state["last_segment_count"] = 0
                st.session_state["error_msg"] = None
                st.rerun()
    else:
        if st.button("⏹️ Arrêter", type="secondary", use_container_width=True):
            api_stop()
            st.session_state["is_recording"] = False
            st.rerun()

if st.session_state.get("error_msg"):
    st.error(st.session_state["error_msg"])

st.markdown("---")

# Polling du backend pour récupérer les segments
if st.session_state["is_recording"]:
    state = fetch_state()
    if state:
        segments = [s for s in state.get("segments", []) if not s.get("is_partial")]
        st.session_state["segments"] = segments
        # Stats
        speakers_stats = state.get("speakers_stats", {})
        st.session_state["stats"] = {
            "speakers": {
                sp: {
                    "total_seconds": d.get("total_seconds", 0),
                    "percentage": d.get("percentage", 0),
                    "word_count": d.get("word_count", 0),
                }
                for sp, d in speakers_stats.items()
            },
            "total_duration": state.get("total_duration", 0),
            "segment_count": len(segments),
            "key_moments_count": len(state.get("key_moments", [])),
        }

left, right = st.columns([2, 1])

MOMENT_COLORS = {"decision": "#10B981", "action": "#F59E0B", "question": "#3B82F6", "risk": "#EF4444"}
MOMENT_EMOJI  = {"decision": "✅", "action": "📌", "question": "❓", "risk": "⚠️"}

with left:
    st.subheader("📝 Transcription")
    segments = st.session_state["segments"]

    if segments:
        for seg in segments:
            mt = seg.get("moment_type")
            color = MOMENT_COLORS.get(mt, "#4F46E5")
            emoji = MOMENT_EMOJI.get(mt, "")
            ts = f"{seg.get('start', 0):.0f}s"
            speaker = seg.get("speaker", "?")
            text = seg.get("text", "")
            st.markdown(
                f'<div style="border-left:4px solid {color};background:#F9FAFB;'
                f'padding:8px 12px;margin:6px 0;border-radius:0 8px 8px 0">'
                f'<small style="color:#6B7280">[{ts}] <strong>{speaker}</strong></small><br>'
                f'{emoji} {text}</div>',
                unsafe_allow_html=True,
            )
    else:
        if st.session_state["is_recording"]:
            st.info("⏳ En attente du premier segment... (3-5 secondes)")
        else:
            st.caption("Cliquez sur Démarrer pour lancer la simulation.")

with right:
    st.subheader("📊 Stats temps réel")
    stats = st.session_state.get("stats", {})
    speakers = stats.get("speakers", {})

    if speakers:
        for sp, data in speakers.items():
            pct = data.get("percentage", 0)
            secs = data.get("total_seconds", 0)
            m, s = int(secs // 60), int(secs % 60)
            st.markdown(f"**{sp}**")
            st.progress(min(pct / 100, 1.0))
            st.caption(f"{m}m{s:02d}s — {pct:.0f}%")
    else:
        st.caption("En attente de données...")

    st.markdown("---")
    st.metric("Segments", len(st.session_state["segments"]))
    st.metric("Moments clés", stats.get("key_moments_count", 0))
    dur = stats.get("total_duration", 0)
    st.metric("Durée", f"{int(dur//60)}m{int(dur%60):02d}s")

# Auto-refresh toutes les 2s pendant l'enregistrement
if st.session_state["is_recording"]:
    time.sleep(2)
    st.rerun()
