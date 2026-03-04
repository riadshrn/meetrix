import os
import requests
import streamlit as st
from pathlib import Path

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.title("📝 Rapport de réunion")

if "current_report" not in st.session_state:
    st.session_state["current_report"] = None
if "report_exports" not in st.session_state:
    st.session_state["report_exports"] = None

def generate_report():
    try:
        with st.spinner("🤖 Génération du rapport par Mistral AI..."):
            r = requests.post(f"{BACKEND}/report", timeout=120)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        st.error("Timeout — réessayez.")
        return None
    except Exception as e:
        st.error(f"Erreur: {e}")
        return None

def fetch_last_report():
    try:
        r = requests.get(f"{BACKEND}/report/last", timeout=5)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    if st.button("🤖 Générer le rapport IA", type="primary", use_container_width=True):
        result = generate_report()
        if result:
            st.session_state["current_report"] = result.get("report")
            st.session_state["report_exports"] = result.get("exports")
            st.success("Rapport généré !")
            st.rerun()
with col2:
    if st.button("📂 Charger dernier rapport", use_container_width=True):
        report = fetch_last_report()
        if report:
            st.session_state["current_report"] = report
            st.success("Rapport chargé.")
            st.rerun()
        else:
            st.info("Aucun rapport disponible.")
with col3:
    if st.session_state["current_report"]:
        if st.button("🗑️ Effacer", use_container_width=True):
            st.session_state["current_report"] = None
            st.rerun()

report = st.session_state.get("current_report")

if not report:
    st.info("Arrêtez d'abord la réunion, puis cliquez sur 'Générer le rapport IA'.")
    with st.expander("ℹ️ Comment ça marche ?"):
        st.markdown("""
1. Démarrez une réunion (page Transcription)
2. Attendez quelques segments
3. Arrêtez l'enregistrement
4. Cliquez **Générer le rapport IA**

Mistral va : résumer, extraire les tâches, identifier les risques.
        """)
    st.stop()

st.markdown(f"## 📋 {report.get('title', 'Rapport')}")
c1, c2, c3 = st.columns(3)
c1.metric("Durée", f"{report.get('duration_minutes', 0):.0f} min")
c2.metric("Participants", len(report.get("participants", [])))
c3.metric("Tâches", len(report.get("action_items", [])))
st.markdown("---")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📄 Résumé", "✅ Décisions", "📌 Tâches", "⚠️ Risques", "📝 Transcription"])

with tab1:
    ctx = report.get("context", "")
    if ctx:
        st.subheader("Contexte")
        st.write(ctx)
    st.subheader("Résumé")
    st.markdown(report.get("summary", "—"))

with tab2:
    decisions = report.get("decisions", [])
    if decisions:
        for i, d in enumerate(decisions, 1):
            st.markdown(f"**{i}.** {d}")
    else:
        st.info("Aucune décision détectée.")
    open_points = report.get("open_points", [])
    if open_points:
        st.subheader("❓ Points ouverts")
        for p in open_points:
            st.markdown(f"- {p}")

with tab3:
    action_items = report.get("action_items", [])
    PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    if action_items:
        for item in action_items:
            priority = item.get("priority", "medium")
            emoji = PRIORITY_EMOJI.get(priority, "⚪")
            due = f" | 📅 {item['due_date']}" if item.get("due_date") else ""
            st.markdown(
                f'<div style="border:1px solid #E5E7EB;border-radius:8px;padding:12px;margin:8px 0">'
                f'<strong>{emoji} {item.get("task","")}</strong><br>'
                f'<small>👤 {item.get("assignee","—")}{due} | Priorité: {priority}</small>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("Aucune tâche extraite.")

with tab4:
    risks = report.get("risks", [])
    if risks:
        for r in risks:
            st.markdown(f"⚠️ {r}")
    else:
        st.info("Aucun risque identifié.")

with tab5:
    transcript = report.get("full_transcript", "")
    if transcript:
        st.text_area("Transcription complète", transcript, height=400)
    else:
        st.info("Transcription non disponible.")

st.markdown("---")
st.subheader("💾 Export")

exports = st.session_state.get("report_exports") or {}
e1, e2 = st.columns(2)

with e1:
    md_path = exports.get("markdown")
    if md_path and Path(md_path).exists():
        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        st.download_button("📄 Télécharger Markdown", data=md_content,
                           file_name=Path(md_path).name, mime="text/markdown", use_container_width=True)
    else:
        st.button("📄 Markdown (non disponible)", disabled=True, use_container_width=True)

with e2:
    pdf_path = exports.get("pdf")
    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        st.download_button("📕 Télécharger PDF", data=pdf_bytes,
                           file_name=Path(pdf_path).name, mime="application/pdf", use_container_width=True)
    else:
        st.info("PDF non disponible (installer reportlab)")
