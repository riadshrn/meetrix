import os
from pathlib import Path

import streamlit as st

_ASSETS      = Path(__file__).parent / "assets"
LOGO         = str(_ASSETS / "logo.png")
LOGO_SIDEBAR = str(_ASSETS / "logo2.png")
LOGO_ICON    = str(_ASSETS / "favicon.png")

st.set_page_config(
    page_title="Meetrix",
    page_icon=LOGO_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.logo(LOGO_SIDEBAR, icon_image=LOGO_ICON, size="large")


def page_accueil():
    st.markdown("""
<style>
    .feat-card {
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        padding: 1.4rem 1rem;
        text-align: center;
        min-height: 180px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
        transition: box-shadow .2s;
    }
    .feat-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.08); }
    .feat-icon  { font-size: 2.2rem; margin-bottom: .6rem; }
    .feat-title { font-weight: 700; font-size: 1rem; margin-bottom: .3rem; }
    .feat-desc  { color: #6B7280; font-size: 0.83rem; line-height: 1.4; }
</style>
""", unsafe_allow_html=True)

    # ── Sidebar config ────────────────────────────────────────────────────────────
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

    # ── Hero ──────────────────────────────────────────────────────────────────────
    _, col_logo, _ = st.columns([1, 1, 1])
    with col_logo:
        st.image(LOGO, use_container_width=True)

    st.markdown(
        '<div style="text-align:center;color:#6B7280;font-size:1rem;'
        'margin-top:-.5rem;margin-bottom:2rem">'
        'Transcription temps réel · Analyse IA · Compte-rendu automatique</div>',
        unsafe_allow_html=True,
    )

    # ── Feature cards ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4, gap="medium")

    with c1:
        st.markdown("""<div class="feat-card">
        <div class="feat-icon">🎙️</div>
        <div class="feat-title">Transcription Live</div>
        <div class="feat-desc">Whisper large-v3-turbo via Groq — transcription quasi-instantanée, diarisation automatique des intervenants</div>
    </div>""", unsafe_allow_html=True)

    with c2:
        st.markdown("""<div class="feat-card">
        <div class="feat-icon">📊</div>
        <div class="feat-title">Statistiques</div>
        <div class="feat-desc">Temps de parole par intervenant, mots clés, moments clés et timeline de la réunion</div>
    </div>""", unsafe_allow_html=True)

    with c3:
        st.markdown("""<div class="feat-card">
        <div class="feat-icon">🤖</div>
        <div class="feat-title">Compte rendu IA</div>
        <div class="feat-desc">Résumé, décisions, points d'action et planification de la prochaine réunion par Mistral AI</div>
    </div>""", unsafe_allow_html=True)

    with c4:
        st.markdown("""<div class="feat-card">
        <div class="feat-icon">💬</div>
        <div class="feat-title">Q&A Assistant</div>
        <div class="feat-desc">Posez des questions sur le contenu de la réunion — réponses contextuelles par Mistral AI</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.info("👈 Naviguez via les pages dans la barre latérale pour démarrer une réunion.")


pg = st.navigation([
    st.Page(page_accueil,                   title="Accueil",                    icon="🏠"),
    st.Page("pages/1_transcription.py",     title="Transcription",              icon="🎙️"),
    st.Page("pages/2_stats.py",             title="Statistiques",               icon="📊"),
    st.Page("pages/3_Compte_rendu.py",      title="Compte rendu",               icon="🤖"),
    st.Page("pages/4_qa.py",               title="Q&A",                        icon="❓"),
])
pg.run()
