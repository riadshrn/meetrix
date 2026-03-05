import os
import re
import time
from collections import Counter, defaultdict

import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

# ── Détection du thème Streamlit ──────────────────────────────────────────────
_theme      = st.get_option("theme.base") or "light"
PLOTLY_TPL  = "plotly_dark" if _theme == "dark" else "plotly_white"
BG_COLOR    = "rgba(0,0,0,0)"
WC_BG       = "#0E1117" if _theme == "dark" else "#FFFFFF"
WC_CMAP     = "cool"    if _theme == "dark" else "Blues"

MOMENT_COLORS = {"decision": "#10B981", "action": "#F59E0B", "question": "#3B82F6", "risk": "#EF4444"}
MOMENT_LABELS = {"decision": "Décision", "action": "Action", "question": "Question", "risk": "Risque"}
MOMENT_EMOJIS = {"decision": "✅", "action": "📌", "question": "❓", "risk": "⚠️"}

STOPWORDS = {
    "le","la","les","un","une","des","du","de","et","en","est","au","aux",
    "ce","se","si","on","il","ils","elle","elles","je","tu","nous","vous",
    "que","qui","quoi","dont","où","par","sur","sous","dans","avec","sans",
    "pour","mais","ou","donc","or","ni","car","plus","bien","très","aussi",
    "comme","pas","ne","à","être","avoir","faire","tout","même","cette",
    "ces","mon","ton","son","ma","ta","sa","mes","tes","ses","nos","vos",
    "leur","leurs","ça","cela","oui","non","alors","après","avant","pendant",
    "quand","parce","ainsi","entre","quel","quelle","était","ont","sont",
    "sera","fait","peu","peut","faut","là","ici","voilà","ok","bien",
}


# ── Fetch état ────────────────────────────────────────────────────────────────
st.title("📊 Statistiques de la réunion")

col_refresh, col_auto = st.columns([1, 3])
with col_refresh:
    if st.button("🔄 Actualiser", type="primary"):
        st.rerun()
with col_auto:
    auto_refresh = st.checkbox("Auto-refresh (5s)", value=False)


def fetch_state():
    try:
        r = requests.get(f"{BACKEND}/state", timeout=15)
        r.raise_for_status()
        return r.json().get("state") or {}
    except Exception as e:
        st.error(f"Impossible de contacter le backend : {e}")
        return {}


state          = fetch_state()

if not state:
    st.info("Aucune réunion en cours. Démarrez une réunion depuis la page Transcription.")
    st.stop()

segments       = [s for s in state.get("segments", []) if not s.get("is_partial")]
speakers_stats = state.get("speakers_stats", {})
keywords       = state.get("keywords", [])
key_moments    = state.get("key_moments", [])
total_dur      = state.get("total_duration", 0)

if not segments:
    st.warning("Aucun segment transcrit pour le moment.")
    st.stop()


# ── 1. KPI cards ──────────────────────────────────────────────────────────────
st.subheader("📋 Vue d'ensemble")

n_decisions = sum(1 for m in key_moments if m.get("moment_type") == "decision")
n_actions   = sum(1 for m in key_moments if m.get("moment_type") == "action")
n_questions = sum(1 for m in key_moments if m.get("moment_type") == "question")
n_risks     = sum(1 for m in key_moments if m.get("moment_type") == "risk")
dur_str     = f"{int(total_dur // 60)}m{int(total_dur % 60):02d}s"

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("⏱️ Durée",        dur_str)
k2.metric("👥 Intervenants", len(speakers_stats))
k3.metric("✅ Décisions",    n_decisions)
k4.metric("📌 Actions",      n_actions)
k5.metric("❓ Questions",    n_questions)
k6.metric("⚠️ Risques",      n_risks)

st.markdown("---")


# ── 2. Engagement & équilibre ─────────────────────────────────────────────────
st.subheader("🗣️ Engagement & temps de parole")

if speakers_stats:
    df_spk = pd.DataFrame([
        {
            "Intervenant":      sp,
            "Durée (min)":      round(d.get("total_seconds", 0) / 60, 2),
            "Pourcentage":      d.get("percentage", 0),
            "Mots":             d.get("word_count", 0),
            "Prises de parole": d.get("segment_count", 0),
        }
        for sp, d in speakers_stats.items()
    ]).sort_values("Durée (min)", ascending=False)

    # Score d'équilibre
    max_pct = df_spk["Pourcentage"].max() if not df_spk.empty else 0
    if len(speakers_stats) <= 1:
        balance_label, balance_color = "Seul intervenant", "#6B7280"
    elif max_pct > 65:
        balance_label, balance_color = "⚠️ Déséquilibrée", "#EF4444"
    elif max_pct > 45:
        balance_label, balance_color = "⚡ Modérément équilibrée", "#F59E0B"
    else:
        balance_label, balance_color = "✅ Bien équilibrée", "#10B981"

    col_pie, col_bar, col_bal = st.columns([1.2, 1.5, 0.9])

    with col_pie:
        fig_pie = px.pie(
            df_spk, values="Durée (min)", names="Intervenant",
            title="Temps de parole",
            color_discrete_sequence=px.colors.qualitative.Set2,
            hole=0.35, template=PLOTLY_TPL,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(showlegend=False, paper_bgcolor=BG_COLOR,
                              margin=dict(t=40, b=10))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_bar:
        fig_bar = px.bar(
            df_spk.sort_values("Prises de parole"),
            x="Prises de parole", y="Intervenant", orientation="h",
            title="Nombre de prises de parole",
            color="Intervenant",
            color_discrete_sequence=px.colors.qualitative.Set2,
            template=PLOTLY_TPL,
        )
        fig_bar.update_layout(showlegend=False, paper_bgcolor=BG_COLOR,
                              margin=dict(t=40, b=10))
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_bal:
        st.markdown("**Équilibre de la réunion**")
        st.markdown(
            f'<div style="border:2px solid {balance_color};border-radius:10px;'
            f'padding:1.2rem;text-align:center;margin:1rem 0">'
            f'<span style="font-size:1rem;font-weight:700;color:{balance_color}">'
            f'{balance_label}</span></div>',
            unsafe_allow_html=True,
        )
        st.dataframe(
            df_spk[["Intervenant", "Pourcentage", "Mots"]].style.format(
                {"Pourcentage": "{:.1f}%"}
            ),
            use_container_width=True, hide_index=True,
        )
else:
    st.info("Pas encore de données de temps de parole.")

st.markdown("---")


# ── 3. Contenu & sujets ───────────────────────────────────────────────────────
st.subheader("💬 Contenu & sujets abordés")

if keywords:
    df_kw  = pd.DataFrame(keywords)
    df_uni = df_kw[~df_kw["is_bigram"]].copy()
    df_bi  = df_kw[df_kw["is_bigram"]].copy()

    col_wc, col_themes = st.columns([1.3, 1])

    with col_wc:
        # Nuage de mots (fallback treemap si wordcloud non installé)
        try:
            from wordcloud import WordCloud
            import matplotlib.pyplot as plt

            freq = {row["term"]: int(row["count"]) for _, row in df_uni.iterrows() if row["count"] > 0}
            if freq:
                wc = WordCloud(
                    width=700, height=350,
                    background_color=WC_BG,
                    colormap=WC_CMAP,
                    max_words=60,
                    prefer_horizontal=0.85,
                ).generate_from_frequencies(freq)
                fig_wc, ax = plt.subplots(figsize=(7, 3.5))
                fig_wc.patch.set_facecolor(WC_BG)
                ax.imshow(wc, interpolation="bilinear")
                ax.axis("off")
                st.markdown("**Nuage de mots**")
                st.pyplot(fig_wc, use_container_width=True)
                plt.close(fig_wc)

        except ImportError:
            # Fallback : treemap Plotly
            fig_tree = px.treemap(
                df_uni.head(30), path=["term"], values="count",
                title="Mots les plus fréquents",
                color="count", color_continuous_scale="Blues",
                template=PLOTLY_TPL,
            )
            fig_tree.update_layout(paper_bgcolor=BG_COLOR, margin=dict(t=40, b=10))
            st.plotly_chart(fig_tree, use_container_width=True)

    with col_themes:
        # Évolution des thèmes : début / milieu / fin
        st.markdown("**Évolution des thèmes**")
        if len(segments) >= 6:
            third = len(segments) // 3
            parts = {
                "🟢 Début":  segments[:third],
                "🟡 Milieu": segments[third: 2 * third],
                "🔴 Fin":    segments[2 * third:],
            }
            for label, segs in parts.items():
                text  = " ".join(s.get("text", "") for s in segs).lower()
                words = re.findall(r"\b[a-zàâäéèêëîïôöùûüç]{3,}\b", text)
                top5  = [w for w, _ in Counter(
                    w for w in words if w not in STOPWORDS
                ).most_common(5)]
                st.markdown(f"**{label}**")
                st.caption(" · ".join(top5) if top5 else "—")
        else:
            st.caption("Pas assez de segments pour l'analyse d'évolution.")

        # Top expressions (bigrammes)
        if not df_bi.empty:
            st.markdown("---")
            st.markdown("**Top expressions**")
            fig_bi = px.bar(
                df_bi.head(8).sort_values("count"),
                x="count", y="term", orientation="h",
                color="count", color_continuous_scale="Purples",
                template=PLOTLY_TPL,
                labels={"count": "Occurrences", "term": ""},
            )
            fig_bi.update_layout(showlegend=False, coloraxis_showscale=False,
                                 paper_bgcolor=BG_COLOR, margin=dict(t=10, b=10))
            st.plotly_chart(fig_bi, use_container_width=True)
else:
    st.info("Pas encore de mots clés.")

st.markdown("---")


# ── 4. Moments clés ───────────────────────────────────────────────────────────
st.subheader("🎯 Moments clés & dynamique")

if key_moments:
    col_heat, col_act = st.columns(2)

    with col_heat:
        # Heatmap : Qui a soulevé quoi ?
        speakers = list(speakers_stats.keys()) if speakers_stats else list(
            {m.get("speaker", "") for m in key_moments}
        )
        types  = list(MOMENT_LABELS.keys())
        matrix = [
            [
                sum(1 for m in key_moments
                    if m.get("speaker") == sp and m.get("moment_type") == mt)
                for mt in types
            ]
            for sp in speakers
        ]
        fig_heat = go.Figure(go.Heatmap(
            z=matrix,
            x=[f"{MOMENT_EMOJIS[t]} {MOMENT_LABELS[t]}" for t in types],
            y=speakers,
            colorscale="Blues",
            showscale=False,
            text=matrix,
            texttemplate="%{text}",
            hovertemplate="Speaker: %{y}<br>Type: %{x}<br>Nb: %{z}<extra></extra>",
        ))
        fig_heat.update_layout(
            title="Qui a soulevé quoi ?",
            template=PLOTLY_TPL, paper_bgcolor=BG_COLOR,
            margin=dict(t=50, b=10), height=300,
        )
        st.plotly_chart(fig_heat, use_container_width=True)

    with col_act:
        # Courbe d'activité : segments par tranche de temps
        if total_dur > 0:
            bucket_size = max(30, int(total_dur / 20))
            buckets: dict = defaultdict(int)
            for seg in segments:
                b = int(seg.get("start", 0) // bucket_size) * bucket_size
                buckets[b] += 1
            max_b  = (int(total_dur // bucket_size) + 1) * bucket_size
            df_act = pd.DataFrame([
                {"Temps (s)": b, "Activité": buckets.get(b, 0)}
                for b in range(0, max_b, bucket_size)
            ])
            fig_act = px.area(
                df_act, x="Temps (s)", y="Activité",
                title="Dynamique de la réunion",
                template=PLOTLY_TPL,
            )
            fig_act.update_traces(fill="tozeroy", line_color="#6366F1",
                                  fillcolor="rgba(99,102,241,0.2)")
            fig_act.update_layout(paper_bgcolor=BG_COLOR,
                                  margin=dict(t=50, b=10), height=300)
            st.plotly_chart(fig_act, use_container_width=True)

    # Timeline
    df_m = pd.DataFrame(key_moments)
    fig_tl = go.Figure()
    for mt, color in MOMENT_COLORS.items():
        sub = df_m[df_m.get("moment_type", pd.Series()) == mt] if "moment_type" in df_m.columns else pd.DataFrame()
        if sub.empty:
            continue
        fig_tl.add_trace(go.Scatter(
            x=sub["timestamp"],
            y=[f"{MOMENT_EMOJIS[mt]} {MOMENT_LABELS[mt]}"] * len(sub),
            mode="markers",
            name=MOMENT_LABELS[mt],
            marker=dict(size=14, color=color, symbol="diamond"),
            text=sub.get("speaker", ""),
            hovertemplate=(
                "<b>%{y}</b><br>Temps : %{x:.0f}s<br>"
                "Speaker : %{text}<extra></extra>"
            ),
        ))
    fig_tl.update_layout(
        title="Timeline des moments importants",
        xaxis_title="Temps (s)",
        template=PLOTLY_TPL, paper_bgcolor=BG_COLOR,
        height=300, margin=dict(t=50, b=10),
    )
    st.plotly_chart(fig_tl, use_container_width=True)

    with st.expander("📋 Liste détaillée des moments clés"):
        for m in key_moments:
            mt    = m.get("moment_type", "")
            color = MOMENT_COLORS.get(mt, "#6B7280")
            label = f"{MOMENT_EMOJIS.get(mt, '')} {MOMENT_LABELS.get(mt, mt)}"
            st.markdown(
                f'<div style="border-left:4px solid {color};padding:6px 12px;'
                f'margin:4px 0;border-radius:0 6px 6px 0">'
                f'<small>[{m.get("timestamp", 0):.0f}s] {label} — '
                f'<strong>{m.get("speaker", "")}</strong></small><br>'
                f'{m.get("text", "")}</div>',
                unsafe_allow_html=True,
            )
else:
    st.info("Aucun moment clé détecté pour l'instant.")


# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(5)
    st.rerun()
