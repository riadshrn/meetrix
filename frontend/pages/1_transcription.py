import os
import queue
import time
import threading
from pathlib import Path

import requests
import numpy as np
import streamlit as st



BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")
WS_URL  = BACKEND.replace("http://", "ws://").replace("https://", "wss://") + "/ws/audio"

SAMPLE_RATE   = 16000
CHUNK_SAMPLES = 8000   # 0.5s par chunk

for k, v in {
    "recording": False,
    "meeting_id": None,
    "error": None,
    "title": "Ma réunion",
    "mode": "real",
    "mic_device": None,
    "mic_validated": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Stop events ──────────────────────────────────────────────────────────────
_inject_stop = threading.Event()
_audio_stop  = threading.Event()


# ── Détection automatique du CABLE Output ───────────────────────────────────
_VIRTUAL_CABLE_KEYWORDS = (
    "cable output",   # VB-Audio CABLE (Windows)
    "vb-audio",       # VB-Audio autres produits (Windows)
    "blackhole",      # BlackHole (macOS)
)

def find_cable_device():
    try:
        import sounddevice as sd
        for i, d in enumerate(sd.query_devices()):
            name = d["name"].lower()
            if d["max_input_channels"] > 0 and any(kw in name for kw in _VIRTUAL_CABLE_KEYWORDS):
                return i, d["name"]
    except Exception:
        pass
    return None, None


# ── Mock mode ────────────────────────────────────────────────────────────────
def _inject_loop():
    while not _inject_stop.is_set():
        time.sleep(3)
        if _inject_stop.is_set():
            break
        try:
            r = requests.post(f"{BACKEND}/demo/inject", timeout=3)
            if r.status_code == 200 and r.json().get("done"):
                break
        except Exception:
            pass


# ── Real mode : mixage 2 sources → WebSocket ─────────────────────────────────
def _audio_loop(mic_idx, cable_idx):
    import sounddevice as sd
    import websocket as ws_client

    mic_q   = queue.Queue(maxsize=200)
    cable_q = queue.Queue(maxsize=200)

    def mic_cb(indata, frames, time_info, status):
        if _audio_stop.is_set():
            raise sd.CallbackStop()
        try:
            mic_q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def cable_cb(indata, frames, time_info, status):
        if _audio_stop.is_set():
            raise sd.CallbackStop()
        try:
            cable_q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    # Stream mic (obligatoire) — boucle de survie si crash
    while not _audio_stop.is_set():
        try:
            # Stream CABLE optionnel : on tente de l'ouvrir, on continue sans si ça échoue
            cable_stream = None
            try:
                cable_stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                              dtype="float32", blocksize=CHUNK_SAMPLES,
                                              device=cable_idx, callback=cable_cb)
                cable_stream.start()
            except Exception:
                cable_stream = None

            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                blocksize=CHUNK_SAMPLES, device=mic_idx, callback=mic_cb):
                ws = None
                while not _audio_stop.is_set():
                    # Reconnexion WebSocket si nécessaire (très rapide sur localhost)
                    if ws is None:
                        try:
                            ws = ws_client.WebSocket()
                            ws.connect(WS_URL)
                        except Exception:
                            ws = None
                            time.sleep(0.2)
                            continue

                    try:
                        mic_chunk = mic_q.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    try:
                        cable_chunk = cable_q.get_nowait()
                        mixed = np.clip(mic_chunk + cable_chunk, -1.0, 1.0)
                    except queue.Empty:
                        mixed = mic_chunk  # micro seul si CABLE silencieux

                    try:
                        ws.send_binary((mixed * 32767).astype(np.int16).tobytes())
                    except Exception:
                        try: ws.close()
                        except Exception: pass
                        ws = None  # reconnexion au prochain tour

        except Exception:
            pass  # stream mic crashé → on relance la boucle de survie
        finally:
            if cable_stream:
                try: cable_stream.stop(); cable_stream.close()
                except Exception: pass
            time.sleep(0.1)  # bref délai avant restart


# ── API helpers ───────────────────────────────────────────────────────────────
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
        requests.post(f"{BACKEND}/stop", timeout=15)
    except Exception as e:
        st.session_state["error"] = str(e)

def api_reset():
    try:
        requests.post(f"{BACKEND}/reset", timeout=5)
    except Exception:
        pass

def get_state():
    try:
        r = requests.get(f"{BACKEND}/state", timeout=5)
        r.raise_for_status()
        return r.json().get("state") or {}
    except Exception as e:
        return {"_error": str(e)}


# ── Fetch état ────────────────────────────────────────────────────────────────
state     = get_state()
segments  = [s for s in state.get("segments", []) if not s.get("is_partial")]
spk_stats = state.get("speakers_stats", {})
total_dur = state.get("total_duration", 0)
key_mom   = state.get("key_moments", [])

if "speaker_mapping" not in st.session_state:
    st.session_state["speaker_mapping"] = {}

def apply_speaker_mapping(name: str) -> str:
    return st.session_state["speaker_mapping"].get(name, name)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Config")
    st.text_input("Backend", value=BACKEND, disabled=True)
    st.session_state["title"] = st.text_input("Titre", value=st.session_state["title"])
    st.markdown("---")
    st.subheader("🎙️ Audio")

    cable_idx, cable_name = find_cable_device()

    try:
        import sounddevice as sd
        devices    = sd.query_devices()

        # Mots-clés qui indiquent un périphérique de sortie (à exclure du sélecteur micro)
        OUTPUT_KEYWORDS = ("speaker", "sortie", "output", "haut-parleur",
                           "playback", "renderer", "écouteur", "casque")

        seen_names = {}
        for i, d in enumerate(devices):
            name      = d["name"]
            name_low  = name.lower()
            is_input  = d["max_input_channels"] > 0
            is_output = any(kw in name_low for kw in OUTPUT_KEYWORDS)
            is_cable  = any(kw in name_low for kw in _VIRTUAL_CABLE_KEYWORDS)
            # Garde les vrais micros, exclut les haut-parleurs ET le cable virtuel (auto-détecté séparément)
            if is_input and not is_output and not is_cable and name not in seen_names:
                seen_names[name] = i
        dev_labels = [f"{idx}: {name}" for name, idx in seen_names.items()]

        # Sélecteur micro physique + bouton Valider
        selected_mic = st.selectbox("🎙️ Mon Micro", dev_labels or ["Aucun détecté"],
                                    disabled=st.session_state["recording"])
        if st.button("✅ Valider le micro", disabled=st.session_state["recording"]):
            if dev_labels:
                st.session_state["mic_device"]    = int(selected_mic.split(":")[0])
                st.session_state["mic_validated"] = True
                st.success(f"Micro validé : {selected_mic}")

        if st.session_state["mic_validated"] and st.session_state["mic_device"] is not None:
            st.caption(f"Micro actif : {st.session_state['mic_device']}")

        # Statut CABLE Output
        if cable_idx is not None:
            st.success(f"✅ Source Meet : {cable_name}")
        else:
            st.error("❌ Source Meet non détectée (BlackHole sur macOS, VB-Audio CABLE sur Windows).")

    except Exception:
        st.warning("sounddevice non disponible")
        cable_idx = None

    # ── Renommer les intervenants ─────────────────────────────────────────────
    raw_speakers = sorted({s.get("speaker", "") for s in segments if s.get("speaker")})
    if raw_speakers:
        st.markdown("---")
        st.subheader("✏️ Intervenants")
        for spk in raw_speakers:
            new_name = st.text_input(spk, value=st.session_state["speaker_mapping"].get(spk, ""),
                                     placeholder=spk, key=f"rename_{spk}")
            if new_name.strip():
                st.session_state["speaker_mapping"][spk] = new_name.strip()
            elif spk in st.session_state["speaker_mapping"]:
                del st.session_state["speaker_mapping"][spk]

    st.markdown("---")
    n = len(segments)
    st.success(f"✅ {n} segment{'s' if n > 1 else ''} reçu{'s' if n > 1 else ''}")
    if state.get("_error"):
        st.error(f"Backend: {state['_error']}")


# ── Titre + boutons ───────────────────────────────────────────────────────────
st.title("🎙️ Transcription Live")

c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])

with c1:
    label = "🔴 **ENREGISTREMENT EN COURS**" if st.session_state["recording"] else "⚫ **EN ATTENTE**"
    badge = "🎙️ Micro réel" if st.session_state["mode"] == "real" else "🤖 Mode Démo"
    st.markdown(f"{label} — {badge}")

with c2:
    if not st.session_state["recording"]:
        ready = st.session_state["mic_validated"] and cable_idx is not None
        if st.button("▶️ Micro réel", type="primary", use_container_width=True, disabled=not ready):
            r = api_start(st.session_state["title"])
            if r:
                st.session_state.update({"recording": True, "mode": "real", "error": None})
                _inject_stop.set()   # stoppe tout thread inject parasite
                _audio_stop.clear()
                t = threading.Thread(
                    target=_audio_loop,
                    args=(st.session_state["mic_device"], cable_idx),
                    daemon=True,
                )
                t.start()
                st.session_state["audio_thread"] = t
                st.rerun()

with c3:
    if not st.session_state["recording"]:
        if st.button("🎭 Démo", type="secondary", use_container_width=True):
            r = api_start(st.session_state["title"])
            if r:
                st.session_state.update({"recording": True, "mode": "mock", "error": None})
                _inject_stop.clear()
                threading.Thread(target=_inject_loop, daemon=True).start()
                st.rerun()

with c4:
    if st.session_state["recording"]:
        if st.button("⏹️ Arrêter", type="secondary", use_container_width=True):
            _inject_stop.set()
            _audio_stop.set()
            with st.spinner("Finalisation de la transcription..."):
                # Attendre que le thread audio ait vraiment fini d'envoyer
                t = st.session_state.get("audio_thread")
                if t and t.is_alive():
                    t.join(timeout=3.0)
                # Donner au backend le temps de recevoir le dernier chunk WebSocket
                time.sleep(0.3)
                try:
                    requests.post(f"{BACKEND}/flush", timeout=15)
                except Exception:
                    pass
            api_stop()
            st.session_state["audio_thread"] = None
            st.session_state["recording"] = False
            st.rerun()

with c5:
    if not st.session_state["recording"] and state:
        if st.button("🔄 Reset", type="secondary", use_container_width=True):
            api_reset()
            st.session_state.update({
                "recording": False, "meeting_id": None,
                "error": None, "mic_validated": False,
            })
            st.rerun()

if st.session_state.get("error"):
    st.error(st.session_state["error"])

st.markdown("---")

# ── Couleurs par locuteur ─────────────────────────────────────────────────────
EMOJIS         = {"decision": "✅", "action": "📌", "question": "❓", "risk": "⚠️"}
SPEAKER_COLORS = ["#6366f1", "#ec4899", "#10b981", "#f59e0b", "#3b82f6", "#8b5cf6", "#ef4444", "#06b6d4"]

_speaker_index: dict = {}
def speaker_color(name: str) -> str:
    if name not in _speaker_index:
        _speaker_index[name] = len(_speaker_index)
    return SPEAKER_COLORS[_speaker_index[name] % len(SPEAKER_COLORS)]

left, right = st.columns([2, 1])

with left:
    st.subheader("📝 Transcription")
    if segments:
        with st.container(height=500):
            for seg in segments:
                mt    = seg.get("moment_type")
                raw_spk = seg.get("speaker", "?")
                spk     = apply_speaker_mapping(raw_spk)
                color   = speaker_color(raw_spk)
                emoji   = EMOJIS.get(mt, "")
                ts      = f"{seg.get('start', 0):.0f}s"
                st.markdown(
                    f'<div style="border-left:4px solid {color};background:#1E1E2E;'
                    f'padding:8px 14px;margin:5px 0;border-radius:0 8px 8px 0">'
                    f'<small style="color:#9CA3AF">[{ts}]</small> '
                    f'<strong style="color:{color}">{spk}</strong><br>'
                    f'<span style="color:#F3F4F6">{emoji} {seg.get("text","")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    elif st.session_state["recording"]:
        st.info("⏳ En attente du premier segment…")
    else:
        st.caption("Cliquez sur ▶️ Micro réel ou 🎭 Démo pour démarrer.")

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

# ── Auto-refresh 2s ───────────────────────────────────────────────────────────
if st.session_state["recording"]:
    time.sleep(2)
    st.rerun()
