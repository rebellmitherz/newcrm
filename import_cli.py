#!/usr/bin/env python
"""CRM Lead-Import per Kommandozeile — für Sandra/OpenClaw.

Liest eine KundenAgent-Datei (CSV/JSON) und spielt sie ins CRM ein.
Einbahnstraße: liest nur, schreibt NIE in den KundenAgent zurück.

Beispiele:
  python import_cli.py "C:\\...\\leads.json" --area "B2B Agenten System" --mode per_industry
  python import_cli.py "C:\\...\\leads.csv"  --area "B2B Agenten System" --mode single --project "Dachdecker Saarbruecken"

Nach dem Import wird crm_export.json aktualisiert (read-only Snapshot für Hermes/Sandra).
"""
from __future__ import annotations

import argparse
import sys

from backend import db, importer, export, main as svc


def run(path: str, area: str | None, mode: str, project: str | None) -> int:
    db.init_db()
    with open(path, "rb") as f:
        data = f.read()
    fmt, raw = importer.parse_bytes(path, data)
    raw, dropped_noise = importer.filter_noise(raw)

    conn = db.get_conn()
    inserted = skipped = 0
    projects: list[str] = []
    try:
        if area:
            db.ensure_area(conn, area)
        if mode in ("per_industry", "per_campaign"):
            groups = (importer.group_by_industry(raw) if mode == "per_industry"
                      else importer.group_by_campaign(raw))
            for label, rows in groups.items():
                pid = svc._ensure_project(conn, name=label, area=area, source=f"KundenAgent ({fmt})")
                projects.append(label)
                i, s = svc._insert_leads(conn, pid, rows, fmt)
                inserted += i
                skipped += s
        else:
            name = (project or f"Import {path.split(chr(92))[-1].split('/')[-1]}").strip()
            pid = svc._ensure_project(conn, name=name, area=area, source=f"KundenAgent ({fmt})")
            projects.append(name)
            i, s = svc._insert_leads(conn, pid, raw, fmt)
            inserted += i
            skipped += s
        conn.commit()
    finally:
        conn.close()
    export.write_snapshot()

    print(f"CRM-IMPORT OK")
    print(f"  format     = {fmt}")
    print(f"  inserted   = {inserted}")
    print(f"  duplicates = {skipped}")
    print(f"  test_noise = {dropped_noise} (verworfen)")
    print(f"  projekte   = {len(projects)}")
    print(f"  bereich    = {area or '(ohne)'}")
    print(f"  export     = crm_export.json aktualisiert")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="CRM Lead-Import (read-only aus KundenAgent)")
    ap.add_argument("file", help="Pfad zu leads.csv / leads.json / B2B_GESAMT_LEADS.json")
    ap.add_argument("--area", default=None, help="Bereich, z.B. 'B2B Agenten System'")
    ap.add_argument("--mode", default="per_industry",
                    choices=["single", "per_industry", "per_campaign"],
                    help="Aufteilung (Standard: per_industry = nach Branche)")
    ap.add_argument("--project", default=None, help="Projektname (nur bei --mode single)")
    args = ap.parse_args()
    try:
        return run(args.file, args.area, args.mode, args.project)
    except FileNotFoundError:
        print(f"FEHLER: Datei nicht gefunden: {args.file}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
