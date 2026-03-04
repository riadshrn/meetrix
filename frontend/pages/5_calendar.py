import os
from pathlib import Path

import requests
import streamlit as st
from datetime import datetime, timedelta

_LOGO      = str(Path(__file__).parent.parent / "assets" / "logo.png")
_LOGO_ICON = str(Path(__file__).parent.parent / "assets" / "logo2.png")
st.set_page_config(page_title="Meetrix", page_icon=_LOGO_ICON, layout="wide")
st.logo(_LOGO, icon_image=_LOGO_ICON, size="large")


BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.title("📅 Planifier la prochaine réunion")

with st.expander("🔧 Configuration Google OAuth (à faire une fois)", expanded=False):
    st.markdown("""
1. Allez sur [Google Cloud Console](https://console.cloud.google.com/)
2. Activez l'**API Google Calendar**
3. Créez credentials OAuth 2.0 → Application de bureau
4. Téléchargez `client_secret.json` → racine du projet
5. Installez : `pip install google-api-python-client google-auth-oauthlib`
6. Premier lancement : autorisation via navigateur → `token.json` créé automatiquement

> Sans `client_secret.json`, le mode **stub** s'active (test sans vraie création d'événement).
    """)

st.markdown("---")
st.subheader("📋 Détails de la prochaine réunion")

with st.form("calendar_form"):
    col1, col2 = st.columns(2)
    with col1:
        meeting_title = st.text_input("Titre", value="Prochaine réunion — Suite")
        default_date = (datetime.now() + timedelta(days=7)).replace(hour=14, minute=0, second=0, microsecond=0)
        meeting_date = st.date_input("Date", value=default_date.date())
        meeting_time = st.time_input("Heure", value=default_date.time())
        duration = st.number_input("Durée (minutes)", min_value=15, max_value=480, value=60, step=15)
    with col2:
        timezone = st.selectbox("Fuseau horaire",
            ["Europe/Paris", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Tokyo"])
        attendees_raw = st.text_area("Participants (un email par ligne)",
            placeholder="alice@company.com\nbob@company.com", height=120)

    submitted = st.form_submit_button("📅 Créer l'événement", type="primary", use_container_width=True)

if submitted:
    try:
        state_r = requests.get(f"{BACKEND}/state", timeout=3)
        meeting_id = (state_r.json().get("state") or {}).get("meeting_id", "unknown")
    except Exception:
        meeting_id = "unknown"

    meeting_datetime = datetime.combine(meeting_date, meeting_time)
    attendees = [e.strip() for e in attendees_raw.strip().split("\n") if e.strip() and "@" in e]

    payload = {
        "meeting_id": meeting_id,
        "next_meeting_title": meeting_title,
        "next_meeting_datetime": meeting_datetime.isoformat(),
        "duration_minutes": int(duration),
        "attendees": attendees,
        "timezone": timezone,
    }

    try:
        with st.spinner("Création de l'événement..."):
            r = requests.post(f"{BACKEND}/calendar", json=payload, timeout=30)
        if r.status_code == 404:
            st.error("Générez d'abord un rapport (page Rapport).")
        else:
            r.raise_for_status()
            result = r.json()
            st.success("✅ Événement créé !")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("### 📅 Détails")
                st.markdown(f"**Titre :** {result.get('summary', meeting_title)}")
                st.markdown(f"**Date :** {meeting_datetime.strftime('%d/%m/%Y à %H:%M')}")
                st.markdown(f"**Durée :** {duration} min")
                if attendees:
                    st.markdown(f"**Invités :** {', '.join(attendees)}")
            with c2:
                st.markdown("### 🔗 Liens")
                html_link = result.get("html_link", "")
                meet_link = result.get("meet_link", "")
                if html_link:
                    st.markdown(f"[📅 Voir dans Google Calendar]({html_link})")
                if meet_link:
                    st.markdown(f"[🎥 Rejoindre via Google Meet]({meet_link})")
            if result.get("event_id") == "stub-event-id":
                st.warning("⚠️ Mode stub — configurez `client_secret.json` pour créer de vrais événements.")
    except Exception as e:
        st.error(f"Erreur : {e}")

with st.sidebar:
    st.subheader("📌 Micro virtuel")
    st.markdown("""
**Windows — VB-Audio Cable**
1. Installer https://vb-audio.com/Cable/
2. Meet → Micro = "CABLE Output"
3. L'app capture l'audio automatiquement

**macOS — BlackHole**
```
brew install blackhole-2ch
```
Créer Multi-Output Device dans Audio MIDI Setup

**Linux — PulseAudio**
```bash
pactl load-module module-null-sink \\
  sink_name=virtual_mic
pactl load-module module-loopback \\
  source=virtual_mic.monitor
```
    """)
