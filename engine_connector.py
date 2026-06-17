#!/usr/bin/env python
"""CRM-Connector — B2B-Engine-Ausgabe → CRM-Import je Mandant (Verbindungsstück ①).

Liest eine fertige Lead-Datei der B2B-Engine (z. B. ``output/latest/hot_leads.json``
oder ``leads.json``) und spielt sie in das CRM EINES Mandanten ein — in dessen
eigene, isolierte ``crm.db``. Dadurch erscheinen die von der Engine gefundenen
Leads automatisch im aufgeräumten CRM des Kunden.

Bewusste Grenzen (siehe FUSION_PLAN.md):
- **Read-only zur Engine.** Es wird NUR die Ausgabedatei gelesen. Kein Import von
  ``b2bbot``, kein Aufruf von ``mine.py``, keine Pipeline-Zustände.
- **Schreibt ausschliesslich** in die CRM-DB des Ziel-Mandanten + dessen Snapshot.
- **Kein Mailversand, kein Auto-Send.** Leads ins eigene CRM schreiben ist KEIN
  „Send".
- Nutzt die vorhandene CRM-Import-Pipeline (``backend.importer/db/export/main``)
  unverändert — das Feld-Mapping erledigt ``importer.FIELD_ALIASES`` bereits.

Aufruf (Test/manuell):
  python engine_connector.py "<...>/hot_leads.json" --db product/data/<mandant>/crm.db \
      --area "B2B Agenten System" --mode per_industry
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from backend import db, importer, export, main as svc


@dataclass
class ConnectorResult:
    ok: bool
    fmt: str = ""
    inserted: int = 0
    duplicates: int = 0
    test_noise: int = 0
    projects: int = 0
    db_path: str = ""
    error: str = ""


def import_engine_output(
    engine_file: str | Path,
    db_path: str | Path,
    *,
    area: str = "B2B Agenten System",
    mode: str = "per_industry",
    project: Optional[str] = None,
) -> ConnectorResult:
    """Importiert eine Engine-Ausgabedatei in die CRM-DB unter ``db_path``.

    Idempotent: Dubletten (E-Mail → Website → Firma+Stadt) werden vom CRM-Importer
    automatisch übersprungen. Mehrfaches Ausführen ist sicher.
    """
    engine_file = Path(engine_file)
    db_path = Path(db_path)

    if not engine_file.exists():
        return ConnectorResult(ok=False, error=f"Engine-Datei fehlt: {engine_file}")

    # DB + Snapshot des Mandanten ansteuern: db.DB_PATH / export.EXPORT_PATH sind
    # Modul-Attribute und werden zur Laufzeit gelesen → ohne db.py zu verändern.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db.DB_PATH = str(db_path)
    export.EXPORT_PATH = str(db_path.parent / "crm_export.json")

    db.init_db()
    data = engine_file.read_bytes()
    fmt, raw = importer.parse_bytes(str(engine_file), data)
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
                pid = svc._ensure_project(conn, name=label, area=area,
                                          source=f"Engine-Connector ({fmt})")
                projects.append(label)
                i, s = svc._insert_leads(conn, pid, rows, fmt)
                inserted += i
                skipped += s
        else:
            name = (project or f"Engine-Import {engine_file.name}").strip()
            pid = svc._ensure_project(conn, name=name, area=area,
                                      source=f"Engine-Connector ({fmt})")
            projects.append(name)
            i, s = svc._insert_leads(conn, pid, raw, fmt)
            inserted += i
            skipped += s
        conn.commit()
    finally:
        conn.close()

    export.write_snapshot()

    return ConnectorResult(
        ok=True, fmt=fmt, inserted=inserted, duplicates=skipped,
        test_noise=dropped_noise, projects=len(projects), db_path=str(db_path),
    )


def main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Engine-Ausgabe in eine Mandanten-CRM-DB importieren (read-only zur Engine)")
    ap.add_argument("engine_file", help="Pfad zu hot_leads.json / leads.json / leads.csv")
    ap.add_argument("--db", required=True,
                    help="Ziel-CRM-DB des Mandanten, z. B. product/data/<mandant>/crm.db")
    ap.add_argument("--area", default="B2B Agenten System")
    ap.add_argument("--mode", default="per_industry",
                    choices=["single", "per_industry", "per_campaign"])
    ap.add_argument("--project", default=None, help="Projektname (nur bei --mode single)")
    args = ap.parse_args()

    r = import_engine_output(args.engine_file, args.db, area=args.area,
                             mode=args.mode, project=args.project)
    print(json.dumps(asdict(r), ensure_ascii=False, indent=2))
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
