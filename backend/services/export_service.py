"""
Service d'export : génération PDF et Markdown du compte-rendu.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.models.meeting import MeetingReport

EXPORT_DIR = Path("exports")
EXPORT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

def generate_markdown(report: MeetingReport) -> str:
    """Génère le compte-rendu au format Markdown."""
    lines = []

    lines.append(f"# Compte-rendu de réunion : {report.title}")
    lines.append(f"\n**Date :** {report.generated_at.strftime('%d/%m/%Y à %H:%M')}")
    lines.append(f"**Durée :** {report.duration_minutes:.0f} minutes")
    if report.participants:
        lines.append(f"**Participants :** {', '.join(report.participants)}")
    lines.append("\n---\n")

    if report.context:
        lines.append("## Contexte\n")
        lines.append(report.context)
        lines.append("")

    if report.decisions:
        lines.append("## Décisions prises\n")
        for d in report.decisions:
            lines.append(f"- {d}")
        lines.append("")

    if report.open_points:
        lines.append("## Points ouverts\n")
        for p in report.open_points:
            lines.append(f"- {p}")
        lines.append("")

    if report.risks:
        lines.append("## Risques identifiés\n")
        for r in report.risks:
            lines.append(f"- {r}")
        lines.append("")

    if report.action_items:
        lines.append("## Tâches et actions\n")
        lines.append("| # | Tâche | Responsable | Échéance | Priorité |")
        lines.append("|---|-------|-------------|----------|----------|")
        for i, item in enumerate(report.action_items, 1):
            due = item.due_date or "—"
            priority = item.priority.value if item.priority else "medium"
            lines.append(f"| {i} | {item.task} | {item.assignee} | {due} | {priority} |")
        lines.append("")

    if report.full_transcript:
        lines.append("## Transcription complète\n")
        lines.append("```")
        lines.append(report.full_transcript[:8000])  # limite taille
        if len(report.full_transcript) > 8000:
            lines.append("\n[...transcription tronquée...]")
        lines.append("```")

    return "\n".join(lines)


def save_markdown(report: MeetingReport) -> Path:
    """Sauvegarde le Markdown et retourne le chemin."""
    md_content = generate_markdown(report)
    filename = f"rapport_{report.meeting_id[:8]}.md"
    filepath = EXPORT_DIR / filename
    filepath.write_text(md_content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# PDF export (via reportlab ou fallback markdown)
# ---------------------------------------------------------------------------

def generate_pdf(report: MeetingReport) -> Optional[Path]:
    """
    Génère un PDF du compte-rendu.
    Utilise reportlab si disponible, sinon retourne None.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        filename = f"rapport_{report.meeting_id[:8]}.pdf"
        filepath = EXPORT_DIR / filename

        doc = SimpleDocTemplate(str(filepath), pagesize=A4,
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        story = []

        # Titre
        title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, spaceAfter=12)
        story.append(Paragraph(f"Compte-rendu : {report.title}", title_style))

        # Méta
        meta = f"Date : {report.generated_at.strftime('%d/%m/%Y %H:%M')} | "
        meta += f"Durée : {report.duration_minutes:.0f} min | "
        meta += f"Participants : {', '.join(report.participants) or '—'}"
        story.append(Paragraph(meta, styles["Normal"]))
        story.append(Spacer(1, 0.5*cm))

        def section(title, items, is_list=True):
            story.append(Paragraph(title, styles["Heading2"]))
            if is_list:
                for item in items:
                    story.append(Paragraph(f"• {item}", styles["Normal"]))
            else:
                story.append(Paragraph(items, styles["Normal"]))
            story.append(Spacer(1, 0.3*cm))

        if report.context:
            section("Contexte", report.context, is_list=False)
        if report.decisions:
            section("Décisions", report.decisions)
        if report.open_points:
            section("Points ouverts", report.open_points)
        if report.risks:
            section("Risques", report.risks)

        # Tableau action items
        if report.action_items:
            story.append(Paragraph("Tâches et actions", styles["Heading2"]))
            table_data = [["Tâche", "Responsable", "Échéance", "Priorité"]]
            for item in report.action_items:
                table_data.append([
                    item.task[:60],
                    item.assignee,
                    item.due_date or "—",
                    item.priority.value if item.priority else "medium",
                ])
            tbl = Table(table_data, colWidths=[8*cm, 4*cm, 3*cm, 2.5*cm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(tbl)

        doc.build(story)
        return filepath

    except ImportError:
        return None


def export_report(report: MeetingReport) -> dict:
    """Exporte en MD + PDF (si disponible). Retourne les chemins."""
    md_path = save_markdown(report)
    pdf_path = generate_pdf(report)
    return {
        "markdown": str(md_path),
        "pdf": str(pdf_path) if pdf_path else None,
    }
