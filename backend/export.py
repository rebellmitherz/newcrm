"""Read-only Snapshot für Hermes/Sandra (Unterwegs-Zugriff).

Schreibt bei jeder Änderung `crm_export.json` in den Projektordner.
Sandra/OpenClaw liest diese Datei lokal — kein API-Zugriff, kein Bot-Coupling.
So kann Hermes per Telegram Lead-Fragen beantworten, wenn Michael unterwegs ist.
"""
from __future__ import annotations

import json
import os
import threading

from . import db

EXPORT_PATH = os.path.join(db.BASE_DIR, "crm_export.json")

# --- Debounce: viele Änderungen (z.B. mehrere Kanban-Drags) → ein Schreibvorgang ---
_DEBOUNCE_SECONDS = 2.0
_lock = threading.Lock()
_timer: threading.Timer | None = None


def request_snapshot() -> None:
    """Plant ein Snapshot-Schreiben (gebündelt). Blockiert den Request nicht."""
    global _timer
    with _lock:
        if _timer is None:
            _timer = threading.Timer(_DEBOUNCE_SECONDS, _flush)
            _timer.daemon = True
            _timer.start()


def _flush() -> None:
    global _timer
    with _lock:
        _timer = None
    write_snapshot()


def flush_now() -> None:
    """Sofort schreiben (z.B. beim Start/Shutdown)."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
    write_snapshot()


def write_snapshot() -> None:
    conn = db.get_conn()
    try:
        projects = [db.dict_from_row(r) for r in conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        )]
        area_names = [r["name"] for r in conn.execute("SELECT name FROM areas ORDER BY name")]
        leads = [db.dict_from_row(r) for r in conn.execute(
            """SELECT id, project_id, company_name, contact_name, role, email, phone,
                      city, website, industry, score, grade, temperature, stage,
                      next_action_label, next_action_date
               FROM leads ORDER BY score IS NULL, score DESC, company_name"""
        )]
    finally:
        conn.close()

    today = db.now_iso()[:10]
    by_stage: dict[str, int] = {s["key"]: 0 for s in db.STAGES}
    overdue = 0
    due_today = 0
    open_stages = {"new", "contacted", "offer"}
    for l in leads:
        by_stage[l["stage"]] = by_stage.get(l["stage"], 0) + 1
        nad = l.get("next_action_date")
        if nad and l["stage"] in open_stages:
            if nad < today:
                overdue += 1
            elif nad == today:
                due_today += 1

    snapshot = {
        "generated_at": db.now_iso(),
        "hinweis": "READ-ONLY Snapshot des CRM. Quelle der Wahrheit ist crm.db. "
                   "Sandra/OpenClaw darf diese Datei lesen, nicht schreiben.",
        "totals": {
            "projekte": len(projects),
            "leads_gesamt": len(leads),
            "mit_email": sum(1 for l in leads if l["email"]),
            "mit_telefon": sum(1 for l in leads if l["phone"]),
            "nach_phase": by_stage,
            "wiedervorlage_ueberfaellig": overdue,
            "wiedervorlage_heute": due_today,
        },
        "bereiche": sorted(set(area_names) | {(p["area"] or "Ohne Bereich") for p in projects}),
        "projekte": [
            {
                "id": p["id"],
                "name": p["name"],
                "bereich": p["area"] or "Ohne Bereich",
                "source": p["source"],
                "leads": sum(1 for l in leads if l["project_id"] == p["id"]),
            }
            for p in projects
        ],
        "leads": leads,
    }

    tmp = EXPORT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    os.replace(tmp, EXPORT_PATH)
