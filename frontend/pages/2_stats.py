import os
from pathlib import Path

import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

_LOGO      = str(Path(__file__).parent.parent / "assets" / "logo.png")
_LOGO_ICON = str(Path(__file__).parent.parent / "assets" / "favicon.png")
st.set_page_config(page_title="Meetrix", page_icon=_LOGO_ICON, layout="wide")
st.logo(_LOGO, icon_image=_LOGO_ICON, size="large")


BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.title("📊 Statistiques de la réunion")

col_refresh, col_auto = st.columns([1, 3])
with col_refresh:
    if st.button("🔄 Actualiser", type="primary"):
        st.rerun()
with col_auto:
    auto_refresh = st.checkbox("Auto-refresh (5s)", value=False)

def fetch_state():
    try:
        r = requests.get(f"{BACKEND}/state", timeout=5)
        r.raise_for_status()
        return r.json().get("state") or {}
    except Exception as e:
        st.error(f"Impossible de contacter le backend : {e}")
        return {}

state = fetch_state()

if not state:
    st.info("Aucune réunion en cours. Démarrez une réunion depuis la page Transcription.")
    st.stop()

segments = state.get("segments", [])
speakers_stats = state.get("speakers_stats", {})
keywords = state.get("keywords", [])
key_moments = state.get("key_moments", [])

if not segments:
    st.warning("Aucun segment transcrit pour le moment.")
    st.stop()

# ---- 1. Temps de parole ----
st.subheader("🗣️ Temps de parole par intervenant")

if speakers_stats:
    df_speakers = pd.DataFrame([
        {
            "Intervenant": sp,
            "Durée (min)": round(data.get("total_seconds", 0) / 60, 2),
            "Pourcentage": data.get("percentage", 0),
            "Mots": data.get("word_count", 0),
        }
        for sp, data in speakers_stats.items()
    ]).sort_values("Durée (min)", ascending=False)

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = px.bar(df_speakers, x="Intervenant", y="Durée (min)", color="Intervenant",
                     text="Pourcentage", title="Temps de parole (minutes)",
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(showlegend=False, plot_bgcolor="white", paper_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig2 = px.pie(df_speakers, values="Durée (min)", names="Intervenant",
                      title="Répartition", color_discrete_sequence=px.colors.qualitative.Set2, hole=0.3)
        fig2.update_traces(textposition="inside", textinfo="percent+label")
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.dataframe(df_speakers.style.format({"Durée (min)": "{:.1f}", "Pourcentage": "{:.1f}%"}),
                 use_container_width=True, hide_index=True)
else:
    st.info("Pas encore de données de temps de parole.")

st.markdown("---")

# ---- 2. Mots clés ----
st.subheader("🔤 Mots et bigrammes les plus fréquents")

if keywords:
    df_kw = pd.DataFrame(keywords)
    df_uni = df_kw[~df_kw["is_bigram"]].head(20)
    df_bi  = df_kw[df_kw["is_bigram"]].head(10)

    kw1, kw2 = st.columns(2)
    with kw1:
        if not df_uni.empty:
            fig3 = px.bar(df_uni.sort_values("count"), x="count", y="term", orientation="h",
                          title="Top 20 mots", color="count", color_continuous_scale="Blues",
                          labels={"count": "Occurrences", "term": "Mot"})
            fig3.update_layout(showlegend=False, coloraxis_showscale=False,
                               plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig3, use_container_width=True)
    with kw2:
        if not df_bi.empty:
            fig4 = px.bar(df_bi.sort_values("count"), x="count", y="term", orientation="h",
                          title="Top bigrammes", color="count", color_continuous_scale="Purples",
                          labels={"count": "Occurrences", "term": "Bigramme"})
            fig4.update_layout(showlegend=False, coloraxis_showscale=False,
                               plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("Pas encore de bigrammes.")
else:
    st.info("Pas encore de mots clés.")

st.markdown("---")

# ---- 3. Timeline moments clés ----
st.subheader("⏱️ Timeline des moments clés")

MOMENT_COLORS = {"decision": "#10B981", "action": "#F59E0B", "question": "#3B82F6", "risk": "#EF4444"}
MOMENT_LABELS = {"decision": "✅ Décision", "action": "📌 Action", "question": "❓ Question", "risk": "⚠️ Risque"}

if key_moments:
    df_m = pd.DataFrame(key_moments)
    fig5 = go.Figure()
    for mt, color in MOMENT_COLORS.items():
        sub = df_m[df_m["moment_type"] == mt]
        if sub.empty:
            continue
        fig5.add_trace(go.Scatter(
            x=sub["timestamp"], y=[MOMENT_LABELS[mt]] * len(sub),
            mode="markers", name=MOMENT_LABELS[mt],
            marker=dict(size=14, color=color, symbol="diamond"),
            text=sub["speaker"],
            hovertemplate="<b>%{y}</b><br>Temps: %{x:.0f}s<br>Speaker: %{text}<extra></extra>",
        ))
    fig5.update_layout(title="Moments importants", xaxis_title="Temps (s)",
                       plot_bgcolor="white", paper_bgcolor="white", height=320)
    st.plotly_chart(fig5, use_container_width=True)

    with st.expander("📋 Liste détaillée"):
        for m in key_moments:
            mt = m.get("moment_type", "")
            color = MOMENT_COLORS.get(mt, "#6B7280")
            label = MOMENT_LABELS.get(mt, "")
            st.markdown(
                f'<div style="border-left:4px solid {color};padding:6px 12px;margin:4px 0;background:#F9FAFB;border-radius:0 6px 6px 0">'
                f'<small>[{m.get("timestamp",0):.0f}s] {label} — <strong>{m.get("speaker","")}</strong></small><br>'
                f'{m.get("text","")}</div>', unsafe_allow_html=True)
else:
    st.info("Aucun moment clé détecté pour l'instant.")

if auto_refresh:
    import time
    time.sleep(5)
    st.rerun()
