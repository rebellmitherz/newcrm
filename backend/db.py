"""SQLite-Datenzugriff für das CRM.

Eine einzige Datei `crm.db` im Projektordner. Bewusst nur stdlib (sqlite3),
keine ORM-Abhängigkeit — die Datei bleibt für Sandra/OpenClaw direkt lesbar.
"""
from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "crm.db")

# Feste Pipeline-Phasen (Reihenfolge = Anzeige im Kanban)
STAGES = [
    {"key": "new", "label": "Neu"},
    {"key": "contacted", "label": "Kontaktiert"},
    {"key": "offer", "label": "Angebot"},
    {"key": "won", "label": "Gewonnen"},
    {"key": "lost", "label": "Verloren"},
]
STAGE_KEYS = {s["key"] for s in STAGES}

ACTIVITY_TYPES = ["note", "call", "email", "meeting", "stage_change", "followup"]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # gleichzeitiges Lesen während Schreibvorgängen
    conn.execute("PRAGMA busy_timeout = 4000")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS areas (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                area        TEXT,
                source      TEXT,
                description TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS leads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                company_name  TEXT,
                contact_name  TEXT,
                role          TEXT,
                email         TEXT,
                phone         TEXT,
                street        TEXT,
                zip           TEXT,
                city          TEXT,
                country       TEXT,
                website       TEXT,
                industry      TEXT,
                score         REAL,
                grade         TEXT,
                temperature   TEXT,
                stage         TEXT NOT NULL DEFAULT 'new',
                dedup_key     TEXT,
                source        TEXT,
                next_action_label TEXT,
                next_action_date  TEXT,
                created_at    TEXT,
                imported_at   TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                raw_json      TEXT,
                UNIQUE(project_id, dedup_key)
            );

            CREATE TABLE IF NOT EXISTS activities (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id    INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                type       TEXT NOT NULL,
                content    TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_leads_project ON leads(project_id);
            CREATE INDEX IF NOT EXISTS idx_leads_stage   ON leads(stage);
            CREATE INDEX IF NOT EXISTS idx_leads_dedup   ON leads(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_act_lead      ON activities(lead_id);
            """
        )
        # Migration: 'area'-Spalte nachrüsten, falls eine ältere DB existiert
        proj_cols = {r["name"] for r in conn.execute("PRAGMA table_info(projects)")}
        if "area" not in proj_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN area TEXT")
        # Migration: Follow-up-Spalten auf bestehenden DBs nachrüsten
        lead_cols = {r["name"] for r in conn.execute("PRAGMA table_info(leads)")}
        if "next_action_label" not in lead_cols:
            conn.execute("ALTER TABLE leads ADD COLUMN next_action_label TEXT")
        if "next_action_date" not in lead_cols:
            conn.execute("ALTER TABLE leads ADD COLUMN next_action_date TEXT")
        # Index auf die (ggf. eben erst angelegte) Follow-up-Spalte
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_nextdate ON leads(next_action_date)")
        conn.commit()
        _backfill_next_action(conn)
    finally:
        conn.close()


def _backfill_next_action(conn: sqlite3.Connection) -> int:
    """Holt die vom KundenAgent vorgeschlagene Aktion einmalig aus raw_json
    in die Spalte next_action_label (nur dort, wo noch leer)."""
    import json
    rows = conn.execute(
        "SELECT id, raw_json FROM leads "
        "WHERE next_action_label IS NULL AND raw_json IS NOT NULL"
    ).fetchall()
    updated = 0
    for r in rows:
        try:
            raw = json.loads(r["raw_json"])
        except (ValueError, TypeError):
            continue
        label = raw.get("next_action_label") or raw.get("next_action")
        if label:
            conn.execute(
                "UPDATE leads SET next_action_label=? WHERE id=?",
                (str(label).strip(), r["id"]),
            )
            updated += 1
    if updated:
        conn.commit()
    return updated


def ensure_area(conn: sqlite3.Connection, name: str) -> None:
    """Bereich anlegen (idempotent)."""
    if not name:
        return
    conn.execute(
        "INSERT OR IGNORE INTO areas (name, created_at) VALUES (?, ?)",
        (name.strip(), now_iso()),
    )


def dict_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}
