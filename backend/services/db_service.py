"""
Persistance SQLite des comptes-rendus (remplace exports/reports_history.json).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.models.meeting import ActionItem, MeetingReport

DB_PATH = Path("meetrix.db")


def init_db():
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            meeting_id       TEXT PRIMARY KEY,
            title            TEXT NOT NULL,
            generated_at     TEXT NOT NULL,
            duration_minutes REAL DEFAULT 0,
            participants     TEXT DEFAULT '[]',
            context          TEXT DEFAULT '',
            summary          TEXT DEFAULT '',
            discussed_points TEXT DEFAULT '[]',
            decisions        TEXT DEFAULT '[]',
            open_points      TEXT DEFAULT '[]',
            risks            TEXT DEFAULT '[]',
            action_items     TEXT DEFAULT '[]',
            full_transcript  TEXT DEFAULT ''
        )""")


def save_report(report: MeetingReport):
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                report.meeting_id,
                report.title,
                report.generated_at.isoformat(),
                report.duration_minutes,
                json.dumps(report.participants),
                report.context,
                report.summary,
                json.dumps(report.discussed_points),
                json.dumps(report.decisions),
                json.dumps(report.open_points),
                json.dumps(report.risks),
                json.dumps([a.model_dump() for a in report.action_items]),
                report.full_transcript,
            ),
        )


def list_reports() -> list[MeetingReport]:
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY generated_at DESC"
        ).fetchall()
    return [_row_to_report(r) for r in rows]


def get_report(meeting_id: str) -> MeetingReport | None:
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM reports WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()
    return _row_to_report(row) if row else None


def delete_report(meeting_id: str) -> bool:
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.execute(
            "DELETE FROM reports WHERE meeting_id = ?", (meeting_id,)
        )
    return cur.rowcount > 0


def _row_to_report(row) -> MeetingReport:
    return MeetingReport(
        meeting_id=row["meeting_id"],
        title=row["title"],
        generated_at=datetime.fromisoformat(row["generated_at"]),
        duration_minutes=row["duration_minutes"],
        participants=json.loads(row["participants"]),
        context=row["context"] or "",
        summary=row["summary"] or "",
        discussed_points=json.loads(row["discussed_points"]),
        decisions=json.loads(row["decisions"]),
        open_points=json.loads(row["open_points"]),
        risks=json.loads(row["risks"]),
        action_items=[ActionItem(**a) for a in json.loads(row["action_items"])],
        full_transcript=row["full_transcript"] or "",
    )
