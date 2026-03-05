import os
import re as _re
import urllib.parse
import uuid as _uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import streamlit as st



BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

# ── CSS minimal (dark-mode safe) ─────────────────────────────────────────────
st.markdown("""
<style>
/* Espacement entre colonnes */
div[data-testid="stHorizontalBlock"] { gap: 10px !important; }
div[data-testid="column"] { padding: 0 !important; }

/* Hero card */
.hero-card {
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 55%, #4338ca 100%);
  border-radius: 14px; padding: 28px 32px; margin-bottom: 16px; color: white;
}
.hero-title { font-size: 1.75rem; font-weight: 700; margin: 0 0 4px 0; }
.hero-meta  { font-size: 0.85rem; opacity: 0.7; margin-bottom: 12px; }
.hero-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.pill {
  background: rgba(255,255,255,0.18); border-radius: 20px;
  padding: 3px 12px; font-size: 0.8rem; font-weight: 500;
}

/* Badges priorité */
.badge {
  display: inline-block; border-radius: 20px;
  padding: 2px 10px; font-size: 0.75rem; font-weight: 600;
}
.badge-high   { background:#fee2e2; color:#b91c1c; }
.badge-medium { background:#fef9c3; color:#a16207; }
.badge-low    { background:#dcfce7; color:#166534; }

/* Avatar participant */
.avatar {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: 50%;
  font-size: 0.78rem; font-weight: 700; color: white; flex-shrink: 0;
}

/* Réduction espacement titre/meta dans les tâches */
div[data-testid="column"] div[data-testid="stMarkdownContainer"] p {
    margin-bottom: 0 !important;
    margin-top: 0 !important;
    line-height: 1.4;
}

/* Bouton Google Tasks */
div[data-testid="stButton"] button[kind="secondary"].gtask {
  border-color: #1a73e8 !important; color: #1a73e8 !important; font-weight: 600;
}

/* Confirmation suppression */
.del-box {
  background: #fef2f2; border: 1px solid #fca5a5;
  border-radius: 10px; padding: 14px 18px; margin: 8px 0;
  color: #7f1d1d;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ────────────────────────────────────────────────────────────
for k, v in {
    "cr_current":        None,
    "cr_edit":           False,
    "cr_edited":         None,
    "cr_tasks_sent":     {},
    "cr_show_hist":      False,
    "cr_delete_confirm": None,
    "cr_hist_search":    "",
    "cal_result":        None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── API ──────────────────────────────────────────────────────────────────────
def api_generate():
    try:
        with st.spinner("Analyse en cours par Mistral AI…"):
            r = requests.post(f"{BACKEND}/report", timeout=120)
        if r.status_code == 404:
            st.warning("⚠️ Aucune réunion disponible. Allez sur la page **Transcription**, démarrez une réunion, attendez quelques segments, puis arrêtez-la avant de générer le compte rendu.")
            return None
        r.raise_for_status()
        return r.json().get("report")
    except requests.exceptions.Timeout:
        st.error("Délai dépassé — réessayez.")
    except Exception as e:
        st.error(f"Erreur : {e}")
    return None


def api_history():
    try:
        r = requests.get(f"{BACKEND}/reports", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def api_delete(mid: str) -> bool:
    try:
        requests.delete(f"{BACKEND}/reports/{mid}", timeout=15).raise_for_status()
        return True
    except Exception as e:
        st.error(f"Erreur suppression : {e}")
        return False


def api_create_task(item: dict, meeting_title: str) -> dict:
    try:
        r = requests.post(f"{BACKEND}/tasks/create", json={
            "task":          item.get("task", ""),
            "assignee":      item.get("assignee", "Non assigné"),
            "due_date":      item.get("due_date"),
            "meeting_title": meeting_title,
        }, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def api_speakers() -> dict:
    try:
        r = requests.get(f"{BACKEND}/state", timeout=3)
        if r.status_code == 200:
            return (r.json().get("state") or {}).get("speakers_stats", {})
    except Exception:
        pass
    return {}


# ── Utils ────────────────────────────────────────────────────────────────────
COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#06b6d4", "#10b981", "#f59e0b", "#ef4444"]

def avatar_color(n): return COLORS[hash(n) % len(COLORS)]
def initials(n):
    p = n.strip().split()
    return (p[0][0] + p[-1][0]).upper() if len(p) >= 2 else n[:2].upper() or "?"

def fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return iso[:10] if iso else "—"

def safe_date(v) -> date | None:
    if not v: return None
    if isinstance(v, date): return v
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()
    except Exception: return None

def mailto_link(report: dict) -> str:
    title = report.get("title", "Compte rendu")
    lines = [f"Compte rendu — {title}", ""]
    if report.get("context"): lines += ["CONTEXTE", report["context"], ""]
    if report.get("decisions"):
        lines += ["DÉCISIONS"] + [f"• {d}" for d in report["decisions"]] + [""]
    if report.get("action_items"):
        lines += ["NEXT STEPS"] + [
            f"• [{a.get('assignee','?')}] {a.get('task','')}" for a in report["action_items"]
        ] + [""]
    if report.get("open_points"):
        lines += ["POINTS OUVERTS"] + [f"• {p}" for p in report["open_points"]]
    return ("mailto:?subject=" + urllib.parse.quote(f"Compte rendu : {title}")
            + "&body=" + urllib.parse.quote("\n".join(lines)))

def _clean(text: str) -> str:
    return _re.sub(r'\*\*(.+?)\*\*', r'\1', text).strip()

PRIO_LABEL  = {"high": "Haute",    "medium": "Moyenne", "low": "Faible"}
PRIO_BADGE  = {"high": "badge-high", "medium": "badge-medium", "low": "badge-low"}
PRIO_TO_FR  = {"high": "🔴 Haute", "medium": "🟡 Moyenne", "low": "🟢 Faible"}
PRIO_FROM_FR = {"🔴 Haute": "high", "🟡 Moyenne": "medium", "🟢 Faible": "low"}


# ══════════════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════════════
st.title("📋 Compte rendu")

# ── Barre d'actions ──────────────────────────────────────────────────────────
c1, c2 = st.columns([2.8, 1.2])
with c1:
    if st.button("Générer le compte rendu IA", type="primary", use_container_width=True):
        result = api_generate()
        if result:
            st.session_state.update({
                "cr_current":    result,
                "cr_edited":     dict(result),
                "cr_edit":       False,
                "cr_tasks_sent": {},
            })
            st.rerun()

with c2:
    if st.button("Historique", use_container_width=True):
        st.session_state["cr_show_hist"] = not st.session_state["cr_show_hist"]
        st.rerun()

# ── Confirmation suppression ─────────────────────────────────────────────────
if st.session_state["cr_delete_confirm"]:
    mid = st.session_state["cr_delete_confirm"]
    st.markdown(
        '<div class="del-box">⚠️ <strong>Supprimer ce compte rendu ?</strong> '
        'Cette action est irréversible.</div>', unsafe_allow_html=True)
    dc1, dc2 = st.columns(2)
    with dc1:
        if st.button("Confirmer la suppression", type="primary", use_container_width=True):
            api_delete(mid)
            st.session_state.update({"cr_current": None, "cr_edit": False, "cr_delete_confirm": None})
            st.rerun()
    with dc2:
        if st.button("Annuler", use_container_width=True):
            st.session_state["cr_delete_confirm"] = None
            st.rerun()

# ── Historique ───────────────────────────────────────────────────────────────
if st.session_state["cr_show_hist"]:
    with st.container(border=True):
        st.markdown("**Historique des comptes rendus**")
        search = st.text_input("Rechercher", placeholder="Nom de réunion, participant…",
                               value=st.session_state["cr_hist_search"],
                               label_visibility="collapsed")
        st.session_state["cr_hist_search"] = search
        history = api_history()
        if search:
            q = search.lower()
            history = [r for r in history if
                       q in r.get("title", "").lower()
                       or any(q in p.lower() for p in r.get("participants", []))]
        if history:
            for r in history:
                mid_r = r.get("meeting_id", "")
                n_ai  = len(r.get("action_items", []))
                n_dec = len(r.get("decisions", []))
                n_p   = len(r.get("participants", []))
                label = f"**{r.get('title','—')}** — {fmt_date(r.get('generated_at',''))} · {n_p} participant(s) · {n_dec} décision(s) · {n_ai} next step(s)"
                with st.expander(label):
                    # Aperçu rapide
                    if r.get("context"):
                        st.caption(f"🎯 {_clean(r['context'])[:180]}…" if len(r.get("context","")) > 180 else f"🎯 {_clean(r['context'])}")
                    if r.get("decisions"):
                        st.markdown("**Décisions :**")
                        for d in r["decisions"][:3]:
                            st.markdown(f"› {_clean(d)}")
                        if len(r["decisions"]) > 3:
                            st.caption(f"+ {len(r['decisions'])-3} autre(s)…")
                    if r.get("action_items"):
                        st.markdown("**Next steps :**")
                        for a in r["action_items"][:3]:
                            st.markdown(f"› [{a.get('assignee','?')}] {a.get('task','')}")
                        if len(r["action_items"]) > 3:
                            st.caption(f"+ {len(r['action_items'])-3} autre(s)…")
                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("Ouvrir ce compte rendu", key=f"hop_{mid_r}", use_container_width=True, type="primary"):
                            st.session_state.update({
                                "cr_current": r, "cr_edited": dict(r),
                                "cr_tasks_sent": {}, "cr_show_hist": False,
                            })
                            st.rerun()
                    with bc2:
                        if st.button("🗑 Supprimer", key=f"hdel_{mid_r}", use_container_width=True):
                            st.session_state.update({"cr_delete_confirm": mid_r, "cr_show_hist": False})
                            st.rerun()
        else:
            st.caption("Aucun compte rendu dans l'historique.")

# ── Guard ────────────────────────────────────────────────────────────────────
report    = st.session_state.get("cr_current")
edited    = st.session_state.get("cr_edited") or {}
edit_mode = st.session_state.get("cr_edit", False)

if not report:
    st.info("Arrêtez d'abord la réunion (page Transcription), puis cliquez sur **Générer le compte rendu IA**.")
    st.stop()

# ── Actions sur le rapport affiché ───────────────────────────────────────────
ra1, ra2 = st.columns([1, 1])
with ra1:
    label = "Sauvegarder" if st.session_state["cr_edit"] else "✏️ Éditer"
    if st.button(label, use_container_width=True):
        if st.session_state["cr_edit"]:
            st.session_state["cr_current"] = dict(st.session_state["cr_edited"])
        st.session_state["cr_edit"] = not st.session_state["cr_edit"]
        st.rerun()
with ra2:
    if not st.session_state["cr_delete_confirm"]:
        if st.button("🗑 Supprimer", use_container_width=True):
            st.session_state["cr_delete_confirm"] = report.get("meeting_id")
            st.rerun()

# ── Données ──────────────────────────────────────────────────────────────────
decisions    = report.get("decisions", [])
action_items = list(report.get("action_items", []))
open_points  = report.get("open_points", [])
participants = report.get("participants", [])
discussed    = report.get("discussed_points", [])
context_text = report.get("context", "")
title        = report.get("title", "Réunion")
meeting_id   = report.get("meeting_id", "")
duration     = report.get("duration_minutes", 0)
speakers     = api_speakers()

# ── HERO ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="hero-card">
  <div class="hero-title">{title}</div>
  <div class="hero-meta">Généré le {fmt_date(report.get('generated_at',''))}</div>
  <div class="hero-pills">
    <span class="pill">⏱ {int(duration)} min</span>
    <span class="pill">👥 {len(participants)} participant{"s" if len(participants)!=1 else ""}</span>
    <span class="pill">✅ {len(decisions)} décision{"s" if len(decisions)!=1 else ""}</span>
    <span class="pill">📌 {len(action_items)} next step{"s" if len(action_items)!=1 else ""}</span>
  </div>
</div>
""", unsafe_allow_html=True)

if edit_mode:
    st.info("✏️ Mode édition actif — modifiez les sections puis cliquez **Sauvegarder**.")

# ── PARTICIPANTS ──────────────────────────────────────────────────────────────
if participants:
    with st.container(border=True):
        rows = ""
        for j, p in enumerate(participants):
            pct = speakers.get(p, {}).get("percentage", 0)
            pct_str = f'<span style="font-size:0.8rem;color:#9ca3af;margin-left:8px">{round(pct)}% du temps de parole</span>' if pct > 0 else ""
            border = "" if j == len(participants) - 1 else "border-bottom:1px solid #f3f4f6"
            rows += (
                f'<div style="display:flex;align-items:center;gap:12px;padding:8px 0;{border}">'
                f'<div class="avatar" style="background:{avatar_color(p)}">{initials(p)}</div>'
                f'<span style="font-weight:600;font-size:0.92rem">{p}</span>{pct_str}'
                f'</div>'
            )
        st.markdown(f'<p style="font-weight:700;margin:0 0 8px 0">👥 Participants</p>{rows}', unsafe_allow_html=True)

# ── CONTEXTE ──────────────────────────────────────────────────────────────────
if edit_mode or context_text:
    with st.container(border=True):
        st.markdown("**🎯 Contexte**")
        if edit_mode:
            edited["context"] = st.text_area(
                "Contexte", value=edited.get("context", context_text),
                key="edit_ctx", height=90, label_visibility="collapsed")
        else:
            st.write(context_text)

# ── POINTS DISCUTÉS ───────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**🗣️ Points discutés**")
    if edit_mode:
        pts_val = "\n".join(edited.get("discussed_points", discussed))
        new_pts = st.text_area("Points discutés", value=pts_val,
                               key="edit_discussed", height=110, label_visibility="collapsed")
        edited["discussed_points"] = [l.lstrip("-•* ") for l in new_pts.splitlines() if l.strip()]
    elif discussed:
        for p in discussed:
            st.markdown(f"› {_clean(p)}")
    else:
        st.caption("Aucun point discuté extrait.")

# ── DÉCISIONS ────────────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**✅ Décisions prises**")
    if edit_mode:
        dec_val = "\n".join(edited.get("decisions", decisions))
        new_dec = st.text_area("Décisions", value=dec_val,
                               key="edit_dec", height=100, label_visibility="collapsed")
        edited["decisions"] = [l.lstrip("-•* ") for l in new_dec.splitlines() if l.strip()]
    elif decisions:
        dec_html = "".join(
            f'<div style="display:flex;align-items:flex-start;gap:10px;padding:7px 0;'
            f'{"" if k == len(decisions)-1 else "border-bottom:1px solid #f0fdf4"}">'
            f'<span style="color:#22c55e;font-size:1rem;flex-shrink:0;margin-top:1px">✓</span>'
            f'<span style="font-size:0.9rem;color:#166534">{_clean(d)}</span></div>'
            for k, d in enumerate(decisions)
        )
        st.markdown(dec_html, unsafe_allow_html=True)
    else:
        st.caption("Aucune décision détectée.")

# ── NEXT STEPS ────────────────────────────────────────────────────────────────
# Initialiser les items édités
if edit_mode and "action_items" not in edited:
    edited["action_items"] = [dict(i) for i in action_items]
work_items = edited.get("action_items", [dict(i) for i in action_items]) if edit_mode else action_items

with st.container(border=True):
    st.markdown("**📌 Next Steps**")

    if work_items:
        for i, item in enumerate(work_items):
            priority  = item.get("priority", "medium")
            assignee  = item.get("assignee", "Non assigné")
            task_text = item.get("task", "")
            due_raw   = item.get("due_date")
            task_id   = item.get("id", str(i))

            if edit_mode:
                del_col, fields_col = st.columns([0.5, 9.5])
                with del_col:
                    if st.button("🗑", key=f"del_task_{i}", help="Supprimer"):
                        edited["action_items"].pop(i)
                        st.rerun()
                with fields_col:
                    f1, f2, f3, f4 = st.columns([2.5, 1.5, 1.5, 1.5])
                    with f1:
                        nt = st.text_input("Tâche", value=task_text, key=f"et_{i}",
                                           label_visibility="collapsed", placeholder="Description de la tâche")
                        edited["action_items"][i]["task"] = nt
                    with f2:
                        opts = ["Non assigné"] + participants
                        idx  = opts.index(assignee) if assignee in opts else 0
                        na = st.selectbox("Assigné", options=opts, index=idx,
                                         key=f"ea_{i}", label_visibility="collapsed")
                        edited["action_items"][i]["assignee"] = na
                    with f3:
                        nd = st.date_input("Échéance", value=safe_date(due_raw),
                                          key=f"ed_{i}", label_visibility="collapsed",
                                          format="DD/MM/YYYY")
                        edited["action_items"][i]["due_date"] = nd.isoformat() if nd else None
                    with f4:
                        prio_opts = ["🔴 Haute", "🟡 Moyenne", "🟢 Faible"]
                        cur_fr = PRIO_TO_FR.get(priority, "🟡 Moyenne")
                        idx_p  = prio_opts.index(cur_fr) if cur_fr in prio_opts else 1
                        np_ = st.selectbox("Priorité", options=prio_opts, index=idx_p,
                                          key=f"ep_{i}", label_visibility="collapsed")
                        edited["action_items"][i]["priority"] = PRIO_FROM_FR.get(np_, "medium")
                st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #e5e7eb">', unsafe_allow_html=True)
            else:
                badge_cls = PRIO_BADGE.get(priority, "badge-medium")
                badge_lbl = PRIO_LABEL.get(priority, priority)
                due_str   = f"📅 {due_raw}" if due_raw else ""
                meta_parts = [f"👤 {assignee}"]
                if due_str: meta_parts.append(due_str)

                col_info, col_btn = st.columns([4, 2])
                with col_info:
                    st.markdown(f"**{task_text}**")
                    badge_html = f'<span class="badge {badge_cls}">{badge_lbl}</span>'
                    st.markdown(
                        " &nbsp;·&nbsp; ".join(meta_parts) + f" &nbsp; {badge_html}",
                        unsafe_allow_html=True)
                with col_btn:
                    already = st.session_state["cr_tasks_sent"].get(task_id)
                    if already:
                        st.success("✓ Ajouté")
                    else:
                        if st.button("Ajouter à Google Tasks", key=f"gtask_{i}",
                                     use_container_width=True):
                            with st.spinner("Ajout en cours…"):
                                res = api_create_task(item, title)
                            if "error" in res:
                                st.error(f"Erreur : {res['error']}")
                            else:
                                st.session_state["cr_tasks_sent"][task_id] = True
                                st.rerun()
                if i < len(work_items) - 1:
                    st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #e5e7eb">', unsafe_allow_html=True)

        if edit_mode:
            if st.button("＋ Ajouter une tâche", key="add_task"):
                edited["action_items"].append({
                    "id": str(_uuid.uuid4()), "task": "", "assignee": "Non assigné",
                    "due_date": None, "priority": "medium", "context": None,
                })
                st.rerun()
    else:
        st.caption("Aucune tâche extraite.")
        if edit_mode and st.button("＋ Ajouter une tâche", key="add_task_empty"):
            edited["action_items"] = [{
                "id": str(_uuid.uuid4()), "task": "", "assignee": "Non assigné",
                "due_date": None, "priority": "medium", "context": None,
            }]
            st.rerun()

# ── POINTS OUVERTS ────────────────────────────────────────────────────────────
with st.container(border=True):
    st.markdown("**❓ Points ouverts**")
    if edit_mode:
        op_val = "\n".join(edited.get("open_points", open_points))
        new_op = st.text_area("Points ouverts", value=op_val,
                              key="edit_op", height=100, label_visibility="collapsed")
        edited["open_points"] = [l.lstrip("-•* ") for l in new_op.splitlines() if l.strip()]
    elif open_points:
        for p in open_points:
            st.warning(p, icon="⚠️")
    else:
        st.success("Aucun point ouvert — réunion bien conclue !", icon="✅")

# ── EXPORT ────────────────────────────────────────────────────────────────────
ec1, ec2, ec3 = st.columns(3)

with ec1:
    try:
        md_bytes = requests.get(f"{BACKEND}/reports/{meeting_id}/markdown", timeout=20).content
        st.download_button("Télécharger en Markdown", data=md_bytes,
                           file_name=f"rapport_{meeting_id[:8]}.md", mime="text/markdown",
                           use_container_width=True)
    except Exception:
        st.button("Télécharger en Markdown", disabled=True, use_container_width=True)

with ec2:
    try:
        pdf_bytes = requests.get(f"{BACKEND}/reports/{meeting_id}/pdf", timeout=20).content
        st.download_button("Télécharger en PDF", data=pdf_bytes,
                           file_name=f"rapport_{meeting_id[:8]}.pdf", mime="application/pdf",
                           use_container_width=True)
    except Exception:
        st.button("Télécharger en PDF", disabled=True, use_container_width=True)

with ec3:
    st.link_button("Envoyer par mail", url=mailto_link(report), use_container_width=True)

# ── PLANIFIER LA PROCHAINE RÉUNION ────────────────────────────────────────────
st.markdown("---")
with st.container(border=True):
    st.markdown("**📅 Planifier la prochaine réunion**")
    with st.form("cal_form_inline"):
        cf1, cf2 = st.columns(2)
        with cf1:
            cal_title    = st.text_input("Titre", value=f"Suite — {title}")
            _default_dt  = (datetime.now() + timedelta(days=7)).replace(hour=14, minute=0, second=0, microsecond=0)
            cal_date     = st.date_input("Date", value=_default_dt.date())
            cal_time     = st.time_input("Heure", value=_default_dt.time())
            cal_duration = st.number_input("Durée (min)", min_value=15, max_value=480, value=60, step=15)
        with cf2:
            cal_tz = st.selectbox("Fuseau horaire",
                ["Europe/Paris", "Europe/London", "America/New_York", "America/Los_Angeles", "Asia/Tokyo"])
            cal_attendees_raw = st.text_area("Participants (un email par ligne)",
                placeholder="alice@company.com\nbob@company.com", height=120)
        cal_submitted = st.form_submit_button("📅 Créer l'événement", type="primary", use_container_width=True)

    if cal_submitted:
        cal_dt       = datetime.combine(cal_date, cal_time)
        cal_attendees = [e.strip() for e in cal_attendees_raw.strip().split("\n") if e.strip() and "@" in e]
        cal_payload  = {
            "meeting_id":           meeting_id or "unknown",
            "next_meeting_title":   cal_title,
            "next_meeting_datetime": cal_dt.isoformat(),
            "duration_minutes":     int(cal_duration),
            "attendees":            cal_attendees,
            "timezone":             cal_tz,
        }
        try:
            with st.spinner("Création de l'événement…"):
                cal_r = requests.post(f"{BACKEND}/calendar", json=cal_payload, timeout=30)
            if cal_r.status_code == 404:
                st.error("Générez d'abord un compte rendu.")
            else:
                cal_r.raise_for_status()
                st.session_state["cal_result"] = cal_r.json()
                st.rerun()
        except requests.exceptions.HTTPError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            st.error(f"Erreur {e.response.status_code} : {detail}")
        except Exception as e:
            st.error(f"Erreur : {e}")

    if st.session_state.get("cal_result"):
        cal_res = st.session_state["cal_result"]
        st.success("✅ Événement créé !")
        lc1, lc2 = st.columns(2)
        with lc1:
            html_link = cal_res.get("html_link", "")
            if html_link:
                st.markdown(f"[📅 Voir dans Google Calendar]({html_link})")
        with lc2:
            meet_link = cal_res.get("meet_link", "")
            if meet_link:
                st.markdown(f"[🎥 Rejoindre via Google Meet]({meet_link})")
        if cal_res.get("event_id") == "stub-event-id":
            st.warning("⚠️ Mode stub — configurez `client_secret.json` pour créer de vrais événements.")
