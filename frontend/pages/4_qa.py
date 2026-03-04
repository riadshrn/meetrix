import os
from pathlib import Path

import requests
import streamlit as st
from datetime import datetime

_LOGO      = str(Path(__file__).parent.parent / "assets" / "logo.png")
_LOGO_ICON = str(Path(__file__).parent.parent / "assets" / "favicon.png")
st.set_page_config(page_title="Meetrix", page_icon=_LOGO_ICON, layout="wide")
st.logo(_LOGO, icon_image=_LOGO_ICON, size="large")


BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.title("❓ Assistant Q&A")
st.caption("Posez des questions sur la réunion — réponses par Mistral AI")

if "qa_history" not in st.session_state:
    st.session_state["qa_history"] = []

def ask_question(question):
    try:
        state_r = requests.get(f"{BACKEND}/state", timeout=3)
        meeting_id = (state_r.json().get("state") or {}).get("meeting_id", "unknown")
        r = requests.post(f"{BACKEND}/qa", json={"question": question, "meeting_id": meeting_id}, timeout=60)
        r.raise_for_status()
        return r.json().get("answer", "Pas de réponse.")
    except requests.exceptions.Timeout:
        return "⚠️ Timeout — le LLM prend trop de temps."
    except Exception as e:
        return f"❌ Erreur : {e}"

# Questions suggérées
with st.expander("💡 Questions suggérées", expanded=True):
    suggestions = [
        "Quelles sont les décisions prises ?",
        "Qui est responsable de quoi ?",
        "Quels sont les risques identifiés ?",
        "Quels sont les points encore ouverts ?",
        "Quelle est la prochaine étape ?",
        "Résume en 3 points clés.",
    ]
    cols = st.columns(2)
    for i, sugg in enumerate(suggestions):
        if cols[i % 2].button(sugg, key=f"sugg_{i}", use_container_width=True):
            st.session_state["pending_question"] = sugg

# Historique
for exchange in st.session_state["qa_history"]:
    with st.chat_message("user"):
        st.write(exchange["question"])
    with st.chat_message("assistant", avatar="🤖"):
        st.write(exchange["answer"])
        st.caption(f"_{exchange['timestamp']}_")

# Input
question = st.chat_input("Posez votre question sur la réunion...")
if "pending_question" in st.session_state:
    question = st.session_state.pop("pending_question")

if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Mistral réfléchit..."):
            answer = ask_question(question)
        st.write(answer)
        ts = datetime.now().strftime("%H:%M:%S")
        st.caption(f"_{ts}_")
    st.session_state["qa_history"].append({
        "question": question, "answer": answer,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })

if st.session_state["qa_history"]:
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑️ Effacer l'historique"):
            st.session_state["qa_history"] = []
            st.rerun()
    with c2:
        history_text = "\n\n".join(
            f"**Q:** {ex['question']}\n**R:** {ex['answer']}"
            for ex in st.session_state["qa_history"]
        )
        st.download_button("💾 Exporter", data=history_text,
                           file_name="qa_history.md", mime="text/markdown")

with st.sidebar:
    st.subheader("💡 Conseils")
    st.markdown("""
- Posez des questions en **français**
- Demandez les **responsables** d'une tâche
- Demandez de **résumer** en 3 points
- Vérifiez des **faits** de la réunion
    """)
    st.info("Le Q&A fonctionne sur la transcription accumulée jusqu'à maintenant.")
