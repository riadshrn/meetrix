import os
import time
import requests
import streamlit as st
from datetime import datetime

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

for k, v in {"recording": False, "meeting_id": None, "error": None, "title": "Ma réunion"}.items():
    if k not in st.session_state:
        st.session_state[k] = v

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

# ── Fetch état backend INCONDITIONNELLEMENT ────────────────────────────────
state = get_state()

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Config")
    st.text_input("Backend", value=BACKEND, disabled=True)
    st.session_state["title"] = st.text_input("Titre", value=st.session_state["title"])
    st.markdown("---")
    st.info("🤖 Mode simulation\nSegment toutes les 3s.")

# ── Titre ──────────────────────────────────────────────────────────────────
st.title("🎙️ Transcription Live")

# ── DEBUG BOX — visible dans l'UI ─────────────────────────────────────────
with st.expander("🔍 DEBUG — état backend brut", expanded=True):
    if state.get("_error"):
        st.error(f"Erreur fetch: {state['_error']}")
    elif not state:
        st.warning("state = vide / None")
    else:
        segs = state.get("segments", [])
        st.write(f"**meeting_id:** `{state.get('meeting_id','?')}`")
        st.write(f"**is_recording:** `{state.get('is_recording','?')}`")
        st.write(f"**started_at:** `{state.get('started_at','?')}`")
        st.write(f"**total_duration:** `{state.get('total_duration','?')}`")
        st.write(f"**segments count:** `{len(segs)}`")
        st.write(f"**speakers_stats keys:** `{list(state.get('speakers_stats',{}).keys())}`")
        st.write(f"**key_moments count:** `{len(state.get('key_moments',[]))}`")
        if segs:
            st.write("**Premier segment:**")
            st.json(segs[0])
        else:
            st.warning("segments = [] — le backend n'a injecté aucun segment encore")
            # Calcul elapsed
            started_at_raw = state.get("started_at")
            if started_at_raw:
                try:
                    started = datetime.fromisoformat(str(started_at_raw).replace("Z","").split(".")[0])
                    elapsed = (datetime.utcnow() - started).total_seconds()
                    expected = min(int(elapsed / 3), 10)
                    st.write(f"**elapsed calculé:** `{elapsed:.1f}s` → devrait avoir `{expected}` segments")
                except Exception as ex:
                    st.write(f"**Erreur parse started_at:** `{ex}`")
                    st.write(f"**started_at raw:** `{repr(started_at_raw)}`")

# ── Boutons ────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([3, 1, 1])
with c1:
    st.markdown("🔴 **EN COURS**" if st.session_state["recording"] else "⚫ **EN ATTENTE**")
with c2:
    if not st.session_state["recording"]:
        if st.button("▶️ Démarrer", type="primary", use_container_width=True):
            r = api_start(st.session_state["title"])
            if r:
                st.session_state["recording"] = True
                st.session_state["meeting_id"] = r["meeting_id"]
                st.session_state["error"] = None
                st.rerun()
with c3:
    if st.session_state["recording"]:
        if st.button("⏹️ Arrêter", type="secondary", use_container_width=True):
            api_stop()
            st.session_state["recording"] = False
            st.rerun()

if st.session_state["error"]:
    st.error(st.session_state["error"])

st.markdown("---")

# ── Affichage transcription ────────────────────────────────────────────────
COLORS = {"decision":"#10B981","action":"#F59E0B","question":"#3B82F6","risk":"#EF4444"}
EMOJIS = {"decision":"✅","action":"📌","question":"❓","risk":"⚠️"}

segments  = [s for s in state.get("segments", []) if not s.get("is_partial")]
spk_stats = state.get("speakers_stats", {})
total_dur = state.get("total_duration", 0)
key_mom   = state.get("key_moments", [])

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
        st.info("⏳ En attente du premier segment...")
    else:
        st.caption("Cliquez sur Démarrer.")

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

if st.session_state["recording"]:
    time.sleep(2)
    st.rerun()
