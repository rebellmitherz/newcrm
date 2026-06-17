#!/usr/bin/env python
"""Einmaliges Nachputzen bereits importierter Leads (Putz-Schicht rückwirkend).

Die Putz-Schicht in ``importer.normalize_lead`` greift nur bei NEUEM Import.
Dieses Skript wendet dieselbe Säuberung auf die SCHON vorhandenen Leads an:
- Firmenname säubern („Name …"-Präfix, Fußzeilen-Text → echter Firmenname)
- Kontaktname von angeklebter Rolle befreien
- Müll-E-Mails (datenschutz@, legal@, noreply@ …) entfernen

Sicher:
- Verändert NUR company_name / contact_name / email (+ dedup_key, kollisionssicher).
- Idempotent: mehrfach ausführbar, bereits saubere Leads bleiben unverändert.
- Lege vorher ein Backup an (crm_backups\\…), das Skript macht KEINS automatisch.

Aufruf:
  python clean_existing_leads.py                 # zeigt nur, was sich ändern würde
  python clean_existing_leads.py --apply          # schreibt die Änderungen
  python clean_existing_leads.py --apply --db crm.db
"""
from __future__ import annotations

import argparse

from backend import db, importer


def _clean_row(row: dict) -> dict | None:
    """Gibt die geänderten Felder zurück oder None, wenn nichts zu tun ist."""
    new_company = importer._clean_company_name(row.get("company_name"))
    new_contact = importer._clean_contact_name(row.get("contact_name"))
    new_email = importer._clean_email(row.get("email"))

    changes: dict = {}
    if new_company != row.get("company_name"):
        changes["company_name"] = new_company
    if new_contact != row.get("contact_name"):
        changes["contact_name"] = new_contact
    if new_email != row.get("email"):
        changes["email"] = new_email
    return changes or None


def run(db_path: str, apply: bool) -> int:
    db.DB_PATH = db_path
    conn = db.get_conn()
    changed = 0
    examined = 0
    try:
        rows = conn.execute("SELECT * FROM leads").fetchall()
        for r in rows:
            examined += 1
            lead = db.dict_from_row(r)
            changes = _clean_row(lead)
            if not changes:
                continue
            changed += 1

            # dedup_key neu berechnen — aber nur, wenn keine Kollision im selben
            # Projekt entsteht (sonst Original-Key behalten, kein UNIQUE-Bruch).
            merged = {**lead, **changes}
            new_key = importer._dedup_key(merged)
            if new_key != lead.get("dedup_key"):
                clash = conn.execute(
                    "SELECT 1 FROM leads WHERE project_id=? AND dedup_key=? AND id<>?",
                    (lead["project_id"], new_key, lead["id"]),
                ).fetchone()
                if not clash:
                    changes["dedup_key"] = new_key

            if changed <= 15:
                old_c = (lead.get("company_name") or "")[:45]
                new_c = (changes.get("company_name", lead.get("company_name")) or "")[:45]
                tag = "" if "company_name" not in changes else f"  Firma: {old_c!r} -> {new_c!r}"
                mail = "" if "email" not in changes else f"  Mail entfernt: {lead.get('email')!r}"
                print(f"[{lead['id']}]{tag}{mail}")

            if apply:
                sets = ", ".join(f"{k}=?" for k in changes)
                params = list(changes.values()) + [db.now_iso(), lead["id"]]
                conn.execute(f"UPDATE leads SET {sets}, updated_at=? WHERE id=?", params)
        if apply:
            conn.commit()
    finally:
        conn.close()

    print()
    print(f"Geprüft: {examined} Leads | zu säubern: {changed}")
    print("MODUS: APPLY (geschrieben)" if apply else "MODUS: Vorschau (nichts geändert) — mit --apply ausführen")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Bestehende CRM-Leads nachträglich säubern")
    ap.add_argument("--db", default=db.DB_PATH, help="Pfad zur crm.db")
    ap.add_argument("--apply", action="store_true", help="Änderungen wirklich schreiben")
    args = ap.parse_args()
    return run(args.db, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
