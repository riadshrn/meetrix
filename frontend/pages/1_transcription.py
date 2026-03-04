import os
import time
import threading
import requests
import streamlit as st

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

for k, v in {"recording": False, "meeting_id": None, "error": None, "title": "Ma réunion"}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Thread qui appelle /demo/inject toutes les 3s ─────────────────────────
_inject_stop = threading.Event()

def _inject_loop():
    """Appelle POST /demo/inject toutes les 3s pour générer des segments."""
    while not _inject_stop.is_set():
        time.sleep(3)
        if _inject_stop.is_set():
            break
        try:
            r = requests.post(f"{BACKEND}/demo/inject", timeout=3)
            if r.status_code == 200:
                data = r.json()
                if data.get("done"):
                    break  # tous les segments injectés
        except Exception:
            pass

def api_start(title):
    try:
        r = requests.post(f"{BACKEND}/start", json={"title": title}, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.session_state["error"] = str(e)
        return None

def api_stop():
    try:
        requests.post(f"{BACKEND}/stop", timeout=5)
    except Exception as e:
        st.session_state["error"] = str(e)

def get_state():
    try:
        r = requests.get(f"{BACKEND}/state", timeout=5)
        r.raise_for_status()
        return r.json().get("state") or {}
    except Exception as e:
        return {"_error": str(e)}

# ── Fetch état backend ─────────────────────────────────────────────────────
state     = get_state()
segments  = [s for s in state.get("segments", []) if not s.get("is_partial")]
spk_stats = state.get("speakers_stats", {})
total_dur = state.get("total_duration", 0)
key_mom   = state.get("key_moments", [])

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Config")
    st.text_input("Backend", value=BACKEND, disabled=True)
    st.session_state["title"] = st.text_input("Titre", value=st.session_state["title"])
    st.markdown("---")
    st.success(f"✅ {len(segments)} segments reçus")
    if state.get("_error"):
        st.error(f"Backend: {state['_error']}")

# ── Titre + boutons ────────────────────────────────────────────────────────
st.title("🎙️ Transcription Live")

c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    st.markdown("🔴 **ENREGISTREMENT EN COURS**" if st.session_state["recording"] else "⚫ **EN ATTENTE**")
with c2:
    if not st.session_state["recording"]:
        if st.button("▶️ Démarrer", type="primary", use_container_width=True):
            r = api_start(st.session_state["title"])
            if r:
                st.session_state["recording"] = True
                st.session_state["error"] = None
                _inject_stop.clear()
                t = threading.Thread(target=_inject_loop, daemon=True)
                t.start()
                st.rerun()
with c3:
    if st.session_state["recording"]:
        if st.button("⏹️ Arrêter", type="secondary", use_container_width=True):
            _inject_stop.set()
            api_stop()
            st.session_state["recording"] = False
            st.rerun()

if st.session_state.get("error"):
    st.error(st.session_state["error"])

st.markdown("---")

# ── Couleurs moments clés ──────────────────────────────────────────────────
COLORS = {"decision":"#10B981","action":"#F59E0B","question":"#3B82F6","risk":"#EF4444"}
EMOJIS = {"decision":"✅","action":"📌","question":"❓","risk":"⚠️"}

left, right = st.columns([2, 1])

with left:
    st.subheader("📝 Transcription")
    if segments:
        for seg in segments:
            mt    = seg.get("moment_type")
            color = COLORS.get(mt, "#4F46E5")
            emoji = EMOJIS.get(mt, "")
            ts    = f"{seg.get('start', 0):.0f}s"
            st.markdown(
                f'<div style="border-left:4px solid {color};background:#F9FAFB;'
                f'padding:8px 14px;margin:5px 0;border-radius:0 8px 8px 0">'
                f'<small style="color:#9CA3AF">[{ts}]</small> '
                f'<strong style="color:#1F2937">{seg.get("speaker","?")}</strong><br>'
                f'{emoji} {seg.get("text","")}',
                unsafe_allow_html=True,
            )
    elif st.session_state["recording"]:
        st.info("⏳ Premier segment dans 3 secondes…")
    else:
        st.caption("Cliquez sur ▶️ Démarrer.")

with right:
    st.subheader("📊 Stats")
    if spk_stats:
        for sp, d in spk_stats.items():
            pct  = d.get("percentage", 0)
            secs = d.get("total_seconds", 0)
            st.markdown(f"**{sp}**")
            st.progress(min(pct / 100, 1.0))
            st.caption(f"{int(secs//60)}m{int(secs%60):02d}s — {pct:.0f}%")
    else:
        st.caption("En attente...")
    st.markdown("---")
    st.metric("Segments",     len(segments))
    st.metric("Moments clés", len(key_mom))
    st.metric("Durée",        f"{int(total_dur//60)}m{int(total_dur%60):02d}s")

# ── Auto-refresh 2s ────────────────────────────────────────────────────────
if st.session_state["recording"]:
    time.sleep(2)
    st.rerun()
