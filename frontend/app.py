import os
import streamlit as st

st.set_page_config(
    page_title="Meeting AI Assistant",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS personnalisé
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 1.5rem;
    }
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    .status-recording {
        background: #FEE2E2;
        color: #DC2626;
        animation: pulse 1.5s infinite;
    }
    .status-idle {
        background: #D1FAE5;
        color: #065F46;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }
    .metric-card {
        background: white;
        border: 1px solid #E5E7EB;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
    }
    .segment-bubble {
        background: #F3F4F6;
        border-left: 4px solid #4F46E5;
        padding: 8px 12px;
        margin: 6px 0;
        border-radius: 0 8px 8px 0;
        font-size: 0.9rem;
    }
    .moment-decision { border-left-color: #10B981; }
    .moment-action { border-left-color: #F59E0B; }
    .moment-question { border-left-color: #3B82F6; }
    .moment-risk { border-left-color: #EF4444; }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div class="main-header">
    <h1 style="margin:0; font-size:1.8rem;">🎙️ Meeting AI Assistant</h1>
    <p style="margin:0.3rem 0 0 0; opacity:0.85;">Transcription temps réel • Analyse IA • Compte-rendu automatique</p>
</div>
""", unsafe_allow_html=True)

# Navigation sidebar
st.sidebar.title("Navigation")
st.sidebar.markdown("---")

pages = {
    "🎙️ Transcription Live": "pages/1_transcription.py",
    "📊 Statistiques": "pages/2_stats.py",
    "📝 Rapport & Export": "pages/3_report.py",
    "❓ Assistant Q&A": "pages/4_qa.py",
    "📅 Google Calendar": "pages/5_calendar.py",
}

# Affiche liens sidebar
for page_name in pages:
    st.sidebar.markdown(f"• {page_name}")

st.sidebar.markdown("---")
st.sidebar.markdown("**Config**")
backend_url = st.sidebar.text_input(
    "URL Backend",
    value=st.session_state.get("backend_url", os.environ.get("BACKEND_URL", "http://localhost:8000")),
    help="URL de l'API FastAPI"
)
if backend_url:
    st.session_state["backend_url"] = backend_url

st.sidebar.markdown("---")
st.sidebar.caption("v1.0.0 | Challenge IA 24h")

# Page d'accueil
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("""
    <div class="metric-card">
        <div style="font-size:2rem">🎙️</div>
        <div style="font-weight:600">Transcription Live</div>
        <div style="color:#6B7280;font-size:0.85rem">Whisper ASR en temps réel</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="metric-card">
        <div style="font-size:2rem">📊</div>
        <div style="font-weight:600">Stats & Graphiques</div>
        <div style="color:#6B7280;font-size:0.85rem">Temps de parole, mots clés</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div class="metric-card">
        <div style="font-size:2rem">🤖</div>
        <div style="font-weight:600">IA Mistral</div>
        <div style="color:#6B7280;font-size:0.85rem">Résumé, tâches, Q&A</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown("""
    <div class="metric-card">
        <div style="font-size:2rem">📅</div>
        <div style="font-weight:600">Google Calendar</div>
        <div style="color:#6B7280;font-size:0.85rem">Prochaine réunion + Meet</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")
st.info("👈 Naviguez via les pages dans la barre latérale, ou lancez directement `streamlit run frontend/pages/1_transcription.py`")