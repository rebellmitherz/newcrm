"""FastAPI-App: eigenständiges Lead-CRM.

Start:  python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765
UI:     http://localhost:8765/

Optionaler Schutz für Handy-/Tunnel-Zugriff: Umgebungsvariable CRM_TOKEN setzen.
Ohne Token läuft alles offen (lokaler Betrieb).
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, importer, export
from . import deliveries as dlv

FRONTEND_DIR = os.path.join(db.BASE_DIR, "frontend")
CRM_TOKEN = os.environ.get("CRM_TOKEN", "").strip()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    export.write_snapshot()
    yield
    export.flush_now()  # ausstehenden Snapshot beim Beenden sicher schreiben


app = FastAPI(title="Rebellsystem CRM", version="1.1", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Auth (optional)
# ---------------------------------------------------------------------------

def require_token(request: Request) -> None:
    if not CRM_TOKEN:
        return
    sent = (
        request.headers.get("X-CRM-Token")
        or request.query_params.get("token")
        or (request.cookies.get("crm_token"))
        or ""
    )
    # konstante Laufzeit → kein Timing-Angriff auf den Token
    if not secrets.compare_digest(sent, CRM_TOKEN):
        raise HTTPException(status_code=401, detail="Ungültiger oder fehlender Token")


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return {
        "stages": db.STAGES,
        "activity_types": db.ACTIVITY_TYPES,
        "auth_required": bool(CRM_TOKEN),
    }


# ---------------------------------------------------------------------------
# Projekte
# ---------------------------------------------------------------------------

class ProjectIn(BaseModel):
    name: str
    area: Optional[str] = None
    source: Optional[str] = "Manuell"
    description: Optional[str] = None


class AreaIn(BaseModel):
    name: str


@app.get("/api/areas", dependencies=[Depends(require_token)])
def list_areas() -> list[dict[str, Any]]:
    """Alle Bereiche inkl. leerer, mit Projekt- und Lead-Anzahl."""
    conn = db.get_conn()
    try:
        names = [r["name"] for r in conn.execute("SELECT name FROM areas ORDER BY name")]
        # Bereiche, die nur an Projekten hängen (Altbestand), ergänzen
        for r in conn.execute("SELECT DISTINCT area FROM projects WHERE area IS NOT NULL AND area<>''"):
            if r["area"] not in names:
                names.append(r["area"])
        out = []
        for name in names:
            row = conn.execute(
                """SELECT COUNT(DISTINCT p.id) pc,
                          (SELECT COUNT(*) FROM leads l JOIN projects p2 ON l.project_id=p2.id WHERE p2.area=?) lc
                   FROM projects p WHERE p.area=?""",
                (name, name),
            ).fetchone()
            out.append({"name": name, "project_count": row["pc"], "lead_count": row["lc"]})
        return out
    finally:
        conn.close()


@app.post("/api/areas", dependencies=[Depends(require_token)])
def create_area(body: AreaIn) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        db.ensure_area(conn, body.name)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "name": body.name.strip()}


@app.get("/api/projects", dependencies=[Depends(require_token)])
def list_projects(area: Optional[str] = None) -> list[dict[str, Any]]:
    conn = db.get_conn()
    try:
        sql = """SELECT p.*,
                      (SELECT COUNT(*) FROM leads l WHERE l.project_id = p.id) AS lead_count
                 FROM projects p"""
        params: list[Any] = []
        if area:
            sql += " WHERE p.area = ?"
            params.append(area)
        sql += " ORDER BY p.area, p.name"
        rows = conn.execute(sql, params).fetchall()
        return [db.dict_from_row(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/projects", dependencies=[Depends(require_token)])
def create_project(body: ProjectIn) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        if body.area:
            db.ensure_area(conn, body.area)
        cur = conn.execute(
            "INSERT INTO projects (name, area, source, description, created_at) VALUES (?,?,?,?,?)",
            (body.name.strip(), (body.area or None), body.source, body.description, db.now_iso()),
        )
        conn.commit()
        pid = cur.lastrowid
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return db.dict_from_row(row)
    finally:
        conn.close()


@app.delete("/api/projects/{pid}", dependencies=[Depends(require_token)])
def delete_project(pid: int) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()
    export.request_snapshot()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

SORTS = {
    "imported_desc": "imported_at DESC",
    "imported_asc": "imported_at ASC",
    "created_desc": "created_at IS NULL, created_at DESC",
    "created_asc": "created_at IS NULL, created_at ASC",
    "score_desc": "score IS NULL, score DESC",
    "company_asc": "company_name COLLATE NOCASE ASC",
    "nextaction_asc": "next_action_date IS NULL, next_action_date ASC",
}

OPEN_STAGES = ("new", "contacted", "offer")


@app.get("/api/leads", dependencies=[Depends(require_token)])
def list_leads(
    project_id: Optional[int] = None,
    area: Optional[str] = None,
    stage: Optional[str] = None,
    q: Optional[str] = None,
    grade: Optional[str] = None,
    due: Optional[str] = None,   # "overdue" | "today" | "week" | "none" | "any"
    kind: Optional[str] = None,  # "signal" | "normal" | None/"all"
    sort: str = "score_desc",
) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if project_id:
        where.append("project_id = ?")
        params.append(project_id)
    if area:
        where.append("project_id IN (SELECT id FROM projects WHERE area = ?)")
        params.append(area)
    if kind == "signal":
        where.append("project_id IN (SELECT id FROM projects WHERE source LIKE '%Signal%')")
    elif kind == "normal":
        where.append("project_id NOT IN (SELECT id FROM projects WHERE source LIKE '%Signal%')")
    if stage:
        where.append("stage = ?")
        params.append(stage)
    if grade:
        where.append("grade = ?")
        params.append(grade)
    if due:
        today = db.now_iso()[:10]
        ph = ",".join("?" * len(OPEN_STAGES))
        if due == "overdue":
            where.append(f"next_action_date < ? AND stage IN ({ph})")
            params.append(today); params.extend(OPEN_STAGES)
        elif due == "today":
            where.append(f"next_action_date = ? AND stage IN ({ph})")
            params.append(today); params.extend(OPEN_STAGES)
        elif due == "week":
            week = _iso_plus_days(7)
            where.append(f"next_action_date >= ? AND next_action_date <= ? AND stage IN ({ph})")
            params.extend([today, week]); params.extend(OPEN_STAGES)
        elif due == "any":
            where.append(f"next_action_date IS NOT NULL AND stage IN ({ph})")
            params.extend(OPEN_STAGES)
        elif due == "none":
            where.append(f"next_action_date IS NULL AND stage IN ({ph})")
            params.extend(OPEN_STAGES)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(company_name LIKE ? ESCAPE '\\' OR contact_name LIKE ? ESCAPE '\\' "
                      "OR email LIKE ? ESCAPE '\\' OR city LIKE ? ESCAPE '\\')")
        params.extend([like, like, like, like])
    sql = "SELECT * FROM leads"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = SORTS.get(sort, SORTS["score_desc"])
    sql += f" ORDER BY {order}, company_name LIMIT 5000"
    conn = db.get_conn()
    try:
        sig_pids = {
            r["id"] for r in
            conn.execute("SELECT id FROM projects WHERE source LIKE '%Signal%'").fetchall()
        }
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = db.dict_from_row(r)
            d["is_signal"] = d.get("project_id") in sig_pids
            out.append(_lead_public(d))
        return out
    finally:
        conn.close()


@app.get("/api/leads/{lid}", dependencies=[Depends(require_token)])
def get_lead(lid: int) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        if not row:
            raise HTTPException(404, "Lead nicht gefunden")
        lead = db.dict_from_row(row)
        acts = conn.execute(
            "SELECT * FROM activities WHERE lead_id=? ORDER BY created_at DESC", (lid,)
        ).fetchall()
        lead["activities"] = [db.dict_from_row(a) for a in acts]
        return lead
    finally:
        conn.close()


class LeadPatch(BaseModel):
    stage: Optional[str] = None
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    street: Optional[str] = None
    zip: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    grade: Optional[str] = None
    next_action_label: Optional[str] = None
    next_action_date: Optional[str] = None   # "YYYY-MM-DD"; "" oder "clear" = entfernen


# Felder, bei denen ein leerer String bewusstes Leeren bedeutet (→ NULL)
_CLEARABLE = {"next_action_date", "next_action_label", "company_name", "contact_name",
              "role", "phone", "email", "street", "zip", "city", "country",
              "website", "grade"}


@app.patch("/api/leads/{lid}", dependencies=[Depends(require_token)])
def patch_lead(lid: int, body: LeadPatch) -> dict[str, Any]:
    raw = {k: v for k, v in body.model_dump().items() if v is not None}
    fields: dict[str, Any] = {}
    for k, v in raw.items():
        if k in _CLEARABLE and v.strip().lower() in ("", "clear"):
            fields[k] = None          # explizit leeren
        else:
            fields[k] = v.strip() if isinstance(v, str) else v
    if "stage" in fields and fields["stage"] not in db.STAGE_KEYS:
        raise HTTPException(400, "Unbekannte Phase")
    if fields.get("next_action_date"):
        d = fields["next_action_date"]
        if len(d) != 10 or d[4] != "-" or d[7] != "-":
            raise HTTPException(400, "Datum muss Format YYYY-MM-DD haben")
    conn = db.get_conn()
    try:
        old = conn.execute(
            "SELECT stage, next_action_date FROM leads WHERE id=?", (lid,)
        ).fetchone()
        if not old:
            raise HTTPException(404, "Lead nicht gefunden")
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            params = list(fields.values()) + [db.now_iso(), lid]
            conn.execute(f"UPDATE leads SET {sets}, updated_at=? WHERE id=?", params)
            # Phasenwechsel als Aktivität protokollieren
            if "stage" in fields and fields["stage"] != old["stage"]:
                label = {s["key"]: s["label"] for s in db.STAGES}
                conn.execute(
                    "INSERT INTO activities (lead_id, type, content, created_at) VALUES (?,?,?,?)",
                    (lid, "stage_change",
                     f"Phase: {label.get(old['stage'], old['stage'])} → {label.get(fields['stage'])}",
                     db.now_iso()),
                )
            # Wiedervorlage gesetzt/geändert protokollieren
            if "next_action_date" in fields and fields["next_action_date"] != old["next_action_date"]:
                msg = (f"Wiedervorlage: {fields['next_action_date']}"
                       if fields["next_action_date"] else "Wiedervorlage entfernt")
                conn.execute(
                    "INSERT INTO activities (lead_id, type, content, created_at) VALUES (?,?,?,?)",
                    (lid, "followup", msg, db.now_iso()),
                )
            conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        result = db.dict_from_row(row)
    finally:
        conn.close()
    export.request_snapshot()
    return result


@app.delete("/api/leads/{lid}", dependencies=[Depends(require_token)])
def delete_lead(lid: int) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM leads WHERE id=?", (lid,))
        conn.commit()
    finally:
        conn.close()
    export.request_snapshot()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Versand-Schutz: Leads als „kontaktiert" markieren (Hermes ruft das nach Mail-Versand)
# ---------------------------------------------------------------------------

class MarkContactedIn(BaseModel):
    lead_ids: list[int]
    postfach: str                       # welches Absender-Postfach gesendet hat
    label: Optional[str] = "Mail 1"     # was gesendet wurde


@app.post("/api/leads/mark-contacted", dependencies=[Depends(require_token)])
def mark_contacted(body: MarkContactedIn) -> dict[str, Any]:
    """Setzt gesendete Leads auf 'contacted' + Versand-Notiz.

    **Idempotent / Doppel-Send-Schutz:** Nur Leads, die noch auf 'new' stehen, werden
    markiert. Ein Lead, der bereits 'contacted' (oder weiter) ist, wird übersprungen –
    so kann derselbe kalte Lead nie ein zweites Mal angeschrieben werden. Hermes ruft das
    direkt nach erfolgreichem Versand auf und überträgt die gesendeten lead_ids + Postfach.
    """
    postfach = (body.postfach or "").strip()
    if not postfach:
        raise HTTPException(400, "postfach (Absender) muss angegeben werden")
    if not body.lead_ids:
        raise HTTPException(400, "Keine lead_ids übergeben")
    label = (body.label or "Mail 1").strip() or "Mail 1"
    stamp = db.now_iso()
    marked: list[int] = []
    skipped: list[dict[str, Any]] = []
    conn = db.get_conn()
    try:
        for lid in body.lead_ids:
            row = conn.execute("SELECT stage FROM leads WHERE id=?", (lid,)).fetchone()
            if not row:
                skipped.append({"id": lid, "grund": "nicht gefunden"})
                continue
            if row["stage"] != "new":
                # schon kontaktiert/weiter → nicht erneut anfassen (Doppel-Send-Schutz)
                skipped.append({"id": lid, "grund": f"schon '{row['stage']}'"})
                continue
            conn.execute(
                "UPDATE leads SET stage='contacted', updated_at=? WHERE id=?", (stamp, lid)
            )
            conn.execute(
                "INSERT INTO activities (lead_id, type, content, created_at) VALUES (?,?,?,?)",
                (lid, "email", f"{label} gesendet · {postfach}", stamp),
            )
            marked.append(lid)
        conn.commit()
    finally:
        conn.close()
    export.request_snapshot()
    return {"ok": True, "marked": marked, "marked_count": len(marked),
            "skipped": skipped, "skipped_count": len(skipped)}


# ---------------------------------------------------------------------------
# Engine / KundenAgent Status
# ---------------------------------------------------------------------------

_ENGINE_LATEST = Path(r"C:\Users\micha\Desktop\KundenAgent\b2bbot\output\latest")
_SIGNAL_FILE = _ENGINE_LATEST / "signal_leads.json"


@app.get("/api/search-status", dependencies=[Depends(require_token)])
def search_status() -> dict[str, Any]:
    """Zählt wie viele Leads aus signal_leads.json noch nicht im CRM sind."""
    import datetime

    if not _SIGNAL_FILE.exists() or _SIGNAL_FILE.stat().st_size <= 2:
        return {"pending": 0, "total_in_file": 0, "file_mtime": None}

    file_mtime = datetime.datetime.fromtimestamp(
        _SIGNAL_FILE.stat().st_mtime
    ).strftime("%Y-%m-%d %H:%M")

    try:
        from backend import importer as _imp
        _, raw = _imp.parse_bytes(_SIGNAL_FILE.name, _SIGNAL_FILE.read_bytes())
    except Exception:
        return {"pending": 0, "total_in_file": 0, "file_mtime": file_mtime, "error": "unlesbar"}

    total_in_file = len(raw)

    if not raw:
        return {"pending": 0, "total_in_file": 0, "file_mtime": file_mtime}

    keys_in_file = {
        _imp.normalize_lead(r)["dedup_key"]
        for r in raw
        if _imp.normalize_lead(r).get("dedup_key")
    }

    conn = db.get_conn()
    try:
        existing = {
            r[0]
            for r in conn.execute(
                "SELECT dedup_key FROM leads WHERE dedup_key IS NOT NULL"
            ).fetchall()
        }
    finally:
        conn.close()

    return {
        "pending": len(keys_in_file - existing),
        "total_in_file": total_in_file,
        "file_mtime": file_mtime,
    }


@app.post("/api/import-engine", dependencies=[Depends(require_token)])
def import_engine() -> dict[str, Any]:
    """Importiert signal_leads.json direkt aus dem KundenAgent-Output ins CRM.

    Alle Treffer EINER Suche landen in EINEM klar benannten Projekt
    (z.B. „Signal: Dachdecker · Berlin") im Bereich „KundenAgent" — so sind sie
    sofort auffindbar und werden nicht über viele Branchen-Projekte verstreut.
    """
    if not _SIGNAL_FILE.exists() or _SIGNAL_FILE.stat().st_size <= 2:
        raise HTTPException(404, "Keine Engine-Datei (signal_leads.json) gefunden")

    data = _SIGNAL_FILE.read_bytes()
    try:
        fmt, raw_leads = importer.parse_bytes(_SIGNAL_FILE.name, data)
    except Exception as e:
        raise HTTPException(400, f"Datei konnte nicht gelesen werden: {e}")

    # Such-Metadaten aus dem Datei-Kopf → sprechender Projektname.
    meta: dict[str, Any] = {}
    try:
        obj = json.loads(importer._decode(data))
        if isinstance(obj, dict):
            meta = obj
    except Exception:
        pass
    zielgruppe = str(meta.get("zielgruppe", "")).strip()
    region = str(meta.get("region", "")).strip()
    if zielgruppe:
        project_name = f"Signal: {zielgruppe}" + (f" · {region}" if region else " · DE")
    else:
        project_name = "Signal-Suche"

    raw_leads, dropped_noise = importer.filter_noise(raw_leads)
    area = "KundenAgent"
    conn = db.get_conn()
    try:
        db.ensure_area(conn, area)
        pid = _ensure_project(conn, name=project_name, area=area,
                              source=f"KundenAgent Signal ({fmt})")
        inserted, skipped = _insert_leads(conn, pid, raw_leads, fmt)
        conn.commit()
    finally:
        conn.close()
    export.request_snapshot()
    return {
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "dropped_noise": dropped_noise,
        "project": project_name,
        "area": area,
        "source_file": _SIGNAL_FILE.name,
    }


# ---------------------------------------------------------------------------
# ClouseAgent-Hook
# ---------------------------------------------------------------------------

CLOUSE_DIR = Path(r"C:\Users\micha\Desktop\ClouseAgent")
CLOUSE_CONTEXT_FILE = CLOUSE_DIR / "lead_context.json"
CLOUSE_SUMMARY_FILE = CLOUSE_DIR / "call_summary.json"


@app.post("/api/leads/{lid}/coach", dependencies=[Depends(require_token)])
def start_coach(lid: int) -> dict[str, Any]:
    """Schreibt Lead-Kontext in ClouseAgent/lead_context.json und gibt Start-Info zurück."""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id=?", (lid,)).fetchone()
        if not row:
            raise HTTPException(404, "Lead nicht gefunden")
        lead = db.dict_from_row(row)
    finally:
        conn.close()

    context = {
        "lead_id": lid,
        "company": lead.get("company_name") or "",
        "contact": lead.get("contact_name") or "",
        "role": lead.get("role") or "",
        "industry": lead.get("industry") or "",
        "city": lead.get("city") or "",
        "website": lead.get("website") or "",
        "email": lead.get("email") or "",
        "phone": lead.get("phone") or "",
        "score": lead.get("score"),
        "grade": lead.get("grade") or "",
        "next_action": lead.get("next_action_label") or "",
        "stage": lead.get("stage") or "",
        "loaded_at": db.now_iso(),
    }

    if not CLOUSE_DIR.exists():
        raise HTTPException(503, f"ClouseAgent-Ordner nicht gefunden: {CLOUSE_DIR}")

    CLOUSE_CONTEXT_FILE.write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"ok": True, "context_written": str(CLOUSE_CONTEXT_FILE), "lead": context}


@app.post("/api/import-call-summary", dependencies=[Depends(require_token)])
def import_call_summary() -> dict[str, Any]:
    """Liest call_summary.json von ClouseAgent und schreibt Transcript als Call-Aktivität in die Timeline."""
    if not CLOUSE_SUMMARY_FILE.exists():
        raise HTTPException(404, "Keine Call-Zusammenfassung gefunden (call_summary.json)")

    try:
        data = json.loads(CLOUSE_SUMMARY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(400, f"call_summary.json unlesbar: {e}")

    lead_id = data.get("lead_id")
    if not lead_id:
        raise HTTPException(400, "Kein lead_id in der Zusammenfassung")

    transcript: list[str] = data.get("transcript", [])
    company = data.get("company", "")
    written_at = data.get("written_at", db.now_iso())

    content = f"Anruf ({len(transcript)} Turns)"
    if company:
        content += f" — {company}"
    if transcript:
        content += "\n\n" + "\n".join(transcript)

    conn = db.get_conn()
    try:
        exists = conn.execute("SELECT 1 FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not exists:
            raise HTTPException(404, f"Lead {lead_id} nicht im CRM gefunden")
        conn.execute(
            "INSERT INTO activities (lead_id, type, content, created_at) VALUES (?,?,?,?)",
            (lead_id, "call", content, db.now_iso()),
        )
        conn.execute("UPDATE leads SET updated_at=? WHERE id=?", (db.now_iso(), lead_id))
        conn.commit()
    finally:
        conn.close()

    # Archivieren statt löschen
    ts = written_at[:19].replace(":", "-").replace("T", "_")
    archive = CLOUSE_DIR / f"call_summary_{ts}.json"
    try:
        CLOUSE_SUMMARY_FILE.rename(archive)
    except Exception:
        pass

    export.request_snapshot()
    return {"ok": True, "lead_id": lead_id, "turns": len(transcript), "archived_as": archive.name}


# ---------------------------------------------------------------------------
# Aktivitäten / Notizen
# ---------------------------------------------------------------------------

class ActivityIn(BaseModel):
    type: str = "note"
    content: str


@app.post("/api/leads/{lid}/activities", dependencies=[Depends(require_token)])
def add_activity(lid: int, body: ActivityIn) -> dict[str, Any]:
    if body.type not in db.ACTIVITY_TYPES:
        raise HTTPException(400, "Unbekannter Aktivitätstyp")
    conn = db.get_conn()
    try:
        exists = conn.execute("SELECT 1 FROM leads WHERE id=?", (lid,)).fetchone()
        if not exists:
            raise HTTPException(404, "Lead nicht gefunden")
        cur = conn.execute(
            "INSERT INTO activities (lead_id, type, content, created_at) VALUES (?,?,?,?)",
            (lid, body.type, body.content.strip(), db.now_iso()),
        )
        conn.execute("UPDATE leads SET updated_at=? WHERE id=?", (db.now_iso(), lid))
        conn.commit()
        row = conn.execute("SELECT * FROM activities WHERE id=?", (cur.lastrowid,)).fetchone()
        return db.dict_from_row(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@app.post("/api/import/preview", dependencies=[Depends(require_token)])
async def import_preview(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    try:
        fmt, raw_leads = importer.parse_bytes(file.filename, data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Datei konnte nicht gelesen werden: {e}")
    raw_leads, dropped_noise = importer.filter_noise(raw_leads)
    normalized = [importer.normalize_lead(r) for r in raw_leads]
    normalized = importer.dedup_within(normalized)
    campaigns = importer.group_by_campaign(raw_leads)
    industries = importer.group_by_industry(raw_leads)
    return {
        "format": fmt,
        "filename": file.filename,
        "total_rows": len(raw_leads) + dropped_noise,
        "dropped_noise": dropped_noise,
        "unique_leads": len(normalized),
        "industry_count": len(industries),
        "campaign_count": len(campaigns),
        "top_industries": sorted(
            ({"name": k, "count": len(v)} for k, v in industries.items()),
            key=lambda x: -x["count"],
        )[:6],
        "sample": [_sample(n) for n in normalized[:5]],
    }


@app.post("/api/import", dependencies=[Depends(require_token)])
async def import_leads(
    file: UploadFile = File(...),
    mode: str = Form("single"),          # "single" | "per_industry" | "per_campaign"
    area: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    project_name: Optional[str] = Form(None),
) -> dict[str, Any]:
    data = await file.read()
    try:
        fmt, raw_leads = importer.parse_bytes(file.filename, data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Datei konnte nicht gelesen werden: {e}")

    raw_leads, dropped_noise = importer.filter_noise(raw_leads)
    area = (area or "").strip() or None
    conn = db.get_conn()
    inserted = 0
    skipped = 0
    created_projects: list[str] = []
    try:
        if area:
            db.ensure_area(conn, area)

        if mode in ("per_industry", "per_campaign"):
            groups = (importer.group_by_industry(raw_leads) if mode == "per_industry"
                      else importer.group_by_campaign(raw_leads))
            for label, rows in groups.items():
                pid = _ensure_project(conn, name=label, area=area, source=f"KundenAgent ({fmt})")
                created_projects.append(label)
                i, s = _insert_leads(conn, pid, rows, fmt)
                inserted += i
                skipped += s
        else:
            if project_id:
                pid = project_id
            else:
                name = (project_name or f"Import {file.filename}").strip()
                pid = _ensure_project(conn, name=name, area=area, source=f"KundenAgent ({fmt})")
                created_projects.append(name)
            i, s = _insert_leads(conn, pid, raw_leads, fmt)
            inserted += i
            skipped += s
        conn.commit()
    finally:
        conn.close()
    export.request_snapshot()
    return {
        "format": fmt,
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "dropped_noise": dropped_noise,
        "projects_created": len(created_projects),
        "area": area,
    }


def _ensure_project(conn, name: str, area: Optional[str], source: str) -> int:
    row = conn.execute(
        "SELECT id FROM projects WHERE name=? AND IFNULL(area,'')=IFNULL(?,'')",
        (name, area),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO projects (name, area, source, description, created_at) VALUES (?,?,?,?,?)",
        (name, area, source, None, db.now_iso()),
    )
    return cur.lastrowid


def _insert_leads(conn, pid: int, raw_rows: list[dict[str, Any]], fmt: str) -> tuple[int, int]:
    inserted = skipped = 0
    now = db.now_iso()
    for raw in raw_rows:
        lead = importer.normalize_lead(raw)
        try:
            conn.execute(
                """INSERT INTO leads
                   (project_id, company_name, contact_name, role, email, phone, street, zip,
                    city, country, website, industry, score, grade, temperature, stage,
                    dedup_key, source, next_action_label, created_at, imported_at, updated_at, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pid, lead["company_name"], lead["contact_name"], lead["role"],
                    lead["email"], lead["phone"], lead["street"], lead["zip"],
                    lead["city"], lead["country"], lead["website"], lead["industry"],
                    lead["score"], lead["grade"], lead["temperature"], "new",
                    lead["dedup_key"], fmt, lead.get("next_action_label"),
                    lead["created_at"], now, now, lead["raw_json"],
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:  # UNIQUE(project_id, dedup_key) = Duplikat
            skipped += 1
    return inserted, skipped


# ---------------------------------------------------------------------------
# Statistik / Dashboard
# ---------------------------------------------------------------------------

@app.get("/api/stats", dependencies=[Depends(require_token)])
def stats(project_id: Optional[int] = None, area: Optional[str] = None) -> dict[str, Any]:
    conds: list[str] = []
    params: list[Any] = []
    if project_id:
        conds.append("project_id=?")
        params.append(project_id)
    if area:
        conds.append("project_id IN (SELECT id FROM projects WHERE area=?)")
        params.append(area)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    and_ = (where + " AND") if where else "WHERE"
    conn = db.get_conn()
    try:
        total = conn.execute(f"SELECT COUNT(*) c FROM leads {where}", params).fetchone()["c"]
        with_email = conn.execute(
            f"SELECT COUNT(*) c FROM leads {and_} email IS NOT NULL AND email<>''",
            params).fetchone()["c"]
        with_phone = conn.execute(
            f"SELECT COUNT(*) c FROM leads {and_} phone IS NOT NULL AND phone<>''",
            params).fetchone()["c"]
        by_stage_rows = conn.execute(
            f"SELECT stage, COUNT(*) c FROM leads {where} GROUP BY stage", params).fetchall()
        by_grade_rows = conn.execute(
            f"SELECT grade, COUNT(*) c FROM leads {where} GROUP BY grade ORDER BY c DESC", params).fetchall()
        today = db.now_iso()[:10]
        ph = ",".join("?" * len(OPEN_STAGES))
        overdue = conn.execute(
            f"SELECT COUNT(*) c FROM leads {and_} next_action_date < ? AND stage IN ({ph})",
            params + [today, *OPEN_STAGES]).fetchone()["c"]
        due_today = conn.execute(
            f"SELECT COUNT(*) c FROM leads {and_} next_action_date = ? AND stage IN ({ph})",
            params + [today, *OPEN_STAGES]).fetchone()["c"]
    finally:
        conn.close()
    by_stage = {s["key"]: 0 for s in db.STAGES}
    for r in by_stage_rows:
        by_stage[r["stage"]] = r["c"]
    won = by_stage.get("won", 0)
    closed = won + by_stage.get("lost", 0)
    return {
        "total": total,
        "with_email": with_email,
        "with_phone": with_phone,
        "by_stage": by_stage,
        "by_grade": [{"grade": r["grade"] or "—", "count": r["c"]} for r in by_grade_rows],
        "conversion_rate": round(won / closed * 100, 1) if closed else 0.0,
        "overdue": overdue,
        "due_today": due_today,
    }


# ---------------------------------------------------------------------------
# Agenda (Wiedervorlagen) & Datenpflege
# ---------------------------------------------------------------------------

@app.get("/api/agenda", dependencies=[Depends(require_token)])
def agenda(project_id: Optional[int] = None, area: Optional[str] = None) -> dict[str, Any]:
    """Leads mit Wiedervorlage, gruppiert in überfällig / heute / diese Woche."""
    conds = ["stage IN ('new','contacted','offer')", "next_action_date IS NOT NULL"]
    params: list[Any] = []
    if project_id:
        conds.append("project_id=?"); params.append(project_id)
    if area:
        conds.append("project_id IN (SELECT id FROM projects WHERE area=?)"); params.append(area)
    where = "WHERE " + " AND ".join(conds)
    today = db.now_iso()[:10]
    week = _iso_plus_days(7)
    conn = db.get_conn()
    try:
        rows = conn.execute(
            f"SELECT * FROM leads {where} ORDER BY next_action_date ASC, score IS NULL, score DESC",
            params).fetchall()
    finally:
        conn.close()
    buckets: dict[str, list[dict[str, Any]]] = {"overdue": [], "today": [], "week": [], "later": []}
    for r in rows:
        lead = _lead_public(db.dict_from_row(r))
        d = lead["next_action_date"]
        if d < today:
            buckets["overdue"].append(lead)
        elif d == today:
            buckets["today"].append(lead)
        elif d <= week:
            buckets["week"].append(lead)
        else:
            buckets["later"].append(lead)
    return {"today_date": today, **buckets,
            "counts": {k: len(v) for k, v in buckets.items()}}


@app.get("/api/duplicates", dependencies=[Depends(require_token)])
def duplicates() -> list[dict[str, Any]]:
    """Firmen, die (über dieselbe dedup_key) in mehreren Projekten liegen."""
    conn = db.get_conn()
    try:
        keys = conn.execute(
            """SELECT dedup_key FROM leads
               WHERE dedup_key IS NOT NULL
               GROUP BY dedup_key
               HAVING COUNT(DISTINCT project_id) > 1
               ORDER BY COUNT(*) DESC"""
        ).fetchall()
        out = []
        for k in keys:
            members = conn.execute(
                """SELECT l.id, l.company_name, l.email, l.city, l.stage,
                          l.project_id, p.name AS project_name, p.area
                   FROM leads l JOIN projects p ON p.id = l.project_id
                   WHERE l.dedup_key = ? ORDER BY p.name""",
                (k["dedup_key"],),
            ).fetchall()
            out.append({
                "dedup_key": k["dedup_key"],
                "company_name": members[0]["company_name"],
                "count": len(members),
                "leads": [db.dict_from_row(m) for m in members],
            })
        return out
    finally:
        conn.close()


@app.post("/api/backup", dependencies=[Depends(require_token)])
def backup() -> dict[str, Any]:
    """Sichere Online-Kopie der crm.db nach crm_backups/."""
    import datetime
    backup_dir = os.path.join(db.BASE_DIR, "crm_backups")
    os.makedirs(backup_dir, exist_ok=True)
    name = "crm-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
    dst_path = os.path.join(backup_dir, name)
    src = db.get_conn()
    try:
        dst = sqlite3.connect(dst_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    size_mb = round(os.path.getsize(dst_path) / 1e6, 2)
    return {"ok": True, "file": name, "size_mb": size_mb}


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def _lead_public(lead: dict[str, Any]) -> dict[str, Any]:
    lead.pop("raw_json", None)
    return lead


def _sample(n: dict[str, Any]) -> dict[str, Any]:
    return {k: n.get(k) for k in ("company_name", "contact_name", "email", "phone", "city", "score", "grade")}


def _iso_plus_days(days: int) -> str:
    import datetime
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Lieferungen — Lead-Bündel pro Kunde + Public-Liefer-Link (1k-Produkt)
# ---------------------------------------------------------------------------

class DeliveryIn(BaseModel):
    title: str
    customer: Optional[str] = None
    note: Optional[str] = None
    lead_ids: list[int]


def _delivery_row_public(row: dict, count: int) -> dict[str, Any]:
    """Lieferungs-Kopf für die interne Liste/Detail (mit Link, ohne Lead-Daten)."""
    return {
        "id": row["id"],
        "title": row["title"],
        "customer": row.get("customer") or "",
        "note": row.get("note") or "",
        "token": row["token"],
        "url": f"/d/{row['token']}",
        "count": count,
        "created_at": row["created_at"],
    }


def _delivery_cards(conn, did: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT l.* FROM delivery_leads dl JOIN leads l ON l.id = dl.lead_id "
        "WHERE dl.delivery_id=? ORDER BY dl.position, l.id",
        (did,),
    ).fetchall()
    return [dlv.build_card(db.dict_from_row(r)) for r in rows]


@app.post("/api/deliveries", dependencies=[Depends(require_token)])
def create_delivery(body: DeliveryIn) -> dict[str, Any]:
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "title fehlt")
    # Reihenfolge erhalten, Dubletten raus
    seen: set[int] = set()
    lead_ids = [i for i in (body.lead_ids or []) if not (i in seen or seen.add(i))]
    if not lead_ids:
        raise HTTPException(400, "Keine lead_ids übergeben")
    token = dlv.gen_token()
    conn = db.get_conn()
    try:
        # nur real existierende Leads verknüpfen
        ph = ",".join("?" * len(lead_ids))
        valid = {r["id"] for r in conn.execute(
            f"SELECT id FROM leads WHERE id IN ({ph})", lead_ids).fetchall()}
        ordered = [i for i in lead_ids if i in valid]
        if not ordered:
            raise HTTPException(404, "Keine der lead_ids existiert")
        cur = conn.execute(
            "INSERT INTO deliveries (token, title, customer, note, created_at) VALUES (?,?,?,?,?)",
            (token, title, (body.customer or None), (body.note or None), db.now_iso()),
        )
        did = cur.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO delivery_leads (delivery_id, lead_id, position) VALUES (?,?,?)",
            [(did, lid, pos) for pos, lid in enumerate(ordered)],
        )
        conn.commit()
        row = db.dict_from_row(conn.execute("SELECT * FROM deliveries WHERE id=?", (did,)).fetchone())
    finally:
        conn.close()
    return {**_delivery_row_public(row, len(ordered)), "skipped_missing": len(lead_ids) - len(ordered)}


@app.get("/api/deliveries", dependencies=[Depends(require_token)])
def list_deliveries() -> list[dict[str, Any]]:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            """SELECT d.*, (SELECT COUNT(*) FROM delivery_leads dl WHERE dl.delivery_id=d.id) AS cnt
               FROM deliveries d ORDER BY d.created_at DESC"""
        ).fetchall()
        return [_delivery_row_public(db.dict_from_row(r), r["cnt"]) for r in rows]
    finally:
        conn.close()


@app.get("/api/deliveries/{did}", dependencies=[Depends(require_token)])
def get_delivery(did: int) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM deliveries WHERE id=?", (did,)).fetchone()
        if not row:
            raise HTTPException(404, "Lieferung nicht gefunden")
        cards = _delivery_cards(conn, did)
        return {**_delivery_row_public(db.dict_from_row(row), len(cards)), "leads": cards}
    finally:
        conn.close()


@app.delete("/api/deliveries/{did}", dependencies=[Depends(require_token)])
def delete_delivery(did: int) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM deliveries WHERE id=?", (did,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


# --- Public (KEIN Login — der Token IST der Zugang) -------------------------

def _public_delivery(token: str) -> dict[str, Any]:
    token = (token or "").strip()
    if not token:
        raise HTTPException(404, "Lieferung nicht gefunden")
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM deliveries WHERE token=?", (token,)).fetchone()
        if not row:
            raise HTTPException(404, "Lieferung nicht gefunden")
        d = db.dict_from_row(row)
        cards = _delivery_cards(conn, d["id"])
    finally:
        conn.close()
    return {
        "title": d["title"],
        "customer": d.get("customer") or "",
        "generated_at": d["created_at"],
        "count": len(cards),
        "leads": cards,
    }


@app.get("/api/public/delivery/{token}")
def public_delivery(token: str) -> dict[str, Any]:
    """Öffentliche Lieferungs-Daten (read-only, kein Login)."""
    return _public_delivery(token)


@app.get("/d/{token}/export.csv")
def public_delivery_csv(token: str):
    from fastapi.responses import Response
    data = _public_delivery(token)
    csv_text = dlv.cards_to_csv(data["leads"])
    fname = "leads_" + (token or "export")[:8] + ".csv"
    return Response(
        content="﻿" + csv_text,   # BOM → Excel öffnet UTF-8 korrekt
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/d/{token}")
def public_delivery_page(token: str) -> FileResponse:
    """Moderne Kundenseite für den Liefer-Link. Token kommt aus dem Pfad; die
    Seite holt die Daten selbst über /api/public/delivery/<token>."""
    return FileResponse(os.path.join(FRONTEND_DIR, "delivery.html"))


# ---------------------------------------------------------------------------
# Frontend (statisch) — am Ende gemountet, damit /api Vorrang hat
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
