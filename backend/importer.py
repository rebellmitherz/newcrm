"""Lead-Import aus dem KundenAgent (CSV / JSON) und generischen Dateien.

Einbahnstraße: liest Dateien, schreibt NIE in den KundenAgent zurück.
Erkennt automatisch die drei bekannten Formate:
  1. KundenAgent leads.csv            (Standardspalten)
  2. KundenAgent leads.json           (Liste reicher Lead-Objekte)
  3. B2B_GESAMT_LEADS.json            (dict mit "leads"-Liste, Gesamtbestand)
und fällt sonst auf generisches CSV/JSON mit Spalten-Mapping zurück.
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

# Mögliche Quell-Feldnamen je Zielfeld (erste Übereinstimmung gewinnt)
FIELD_ALIASES: dict[str, list[str]] = {
    "company_name": ["company_name", "canonical_company_name", "firma", "company", "name"],
    "contact_name": ["contact_full_name", "managing_director", "contact_name", "ansprechpartner"],
    "role": ["role", "position", "rolle"],
    "email": ["email", "e-mail", "mail", "email_address"],
    "phone": ["phone", "telefon", "tel", "phone_number"],
    "street": ["street", "strasse", "straße", "address"],
    "zip": ["zip", "plz", "postal_code", "postleitzahl"],
    "city": ["city", "city_detected", "stadt", "ort"],
    "country": ["country", "land"],
    "website": ["website", "source_url", "url", "webseite"],
    "industry": ["industry", "industry_group", "branche"],
    "grade": ["lead_status", "lead_class", "lead_priority", "grade"],
    "temperature": ["lead_temperature", "temperature"],
    "next_action_label": ["next_action_label", "next_action", "naechster_schritt"],
    "created_at": ["created_at", "erstellt", "date"],
}

SCORE_FIELDS = [
    "score",
    "contact_quality_score",
    "revenue_fit_score",
    "client_potential_score",
]


def _first(d: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    # case-insensitive Fallback
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in low and low[k.lower()] not in (None, ""):
            return low[k.lower()]
    return None


def _score(d: dict[str, Any]) -> float | None:
    for k in SCORE_FIELDS:
        v = _first(d, [k])
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _build_contact_name(d: dict[str, Any]) -> str | None:
    name = _first(d, FIELD_ALIASES["contact_name"])
    if name:
        return str(name).strip()
    first = _first(d, ["contact_first_name", "first_name", "vorname"])
    last = _first(d, ["contact_last_name", "last_name", "nachname"])
    parts = [p for p in [first, last] if p]
    return " ".join(str(p).strip() for p in parts) if parts else None


def _norm_temperature(raw: dict[str, Any]) -> str | None:
    t = _first(raw, FIELD_ALIASES["temperature"])
    if t:
        return str(t).lower()
    # Heuristik aus is_premium_lead / Grade
    if raw.get("is_premium_lead") is True:
        return "hot"
    return None


def normalize_lead(raw: dict[str, Any]) -> dict[str, Any]:
    """Wandelt ein beliebiges Quell-Lead in das CRM-Schema."""
    lead = {
        "company_name": _clean(_first(raw, FIELD_ALIASES["company_name"])),
        "contact_name": _clean(_build_contact_name(raw)),
        "role": _clean(_first(raw, FIELD_ALIASES["role"])),
        "email": _clean_email(_first(raw, FIELD_ALIASES["email"])),
        "phone": _clean(_first(raw, FIELD_ALIASES["phone"])),
        "street": _clean(_first(raw, FIELD_ALIASES["street"])),
        "zip": _clean(_first(raw, FIELD_ALIASES["zip"])),
        "city": _clean(_first(raw, FIELD_ALIASES["city"])),
        "country": _clean(_first(raw, FIELD_ALIASES["country"])),
        "website": _clean(_first(raw, FIELD_ALIASES["website"])),
        "industry": _clean(_first(raw, FIELD_ALIASES["industry"])),
        "score": _score(raw),
        "grade": _clean(_first(raw, FIELD_ALIASES["grade"])),
        "temperature": _norm_temperature(raw),
        "next_action_label": _clean(_first(raw, FIELD_ALIASES["next_action_label"])),
        "created_at": _clean(_first(raw, FIELD_ALIASES["created_at"])),
        "raw_json": json.dumps(raw, ensure_ascii=False),
    }
    lead["dedup_key"] = _dedup_key(lead)
    return lead


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _clean_email(v: Any) -> str | None:
    s = _clean(v)
    return s.lower() if s else None


def _dedup_key(lead: dict[str, Any]) -> str:
    """Stabiler Schlüssel: E-Mail > Website-Domain > Firma+Stadt."""
    if lead.get("email"):
        return "email:" + lead["email"]
    if lead.get("website"):
        dom = re.sub(r"^https?://(www\.)?", "", lead["website"].lower()).strip("/")
        dom = dom.split("/")[0]
        if dom:
            return "web:" + dom
    company = (lead.get("company_name") or "").lower().strip()
    city = (lead.get("city") or "").lower().strip()
    return "name:" + company + "|" + city


# ---------------------------------------------------------------------------
# Datei-Parser
# ---------------------------------------------------------------------------

def parse_bytes(filename: str, data: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Gibt (erkanntes_format, [roh_leads]) zurück."""
    name = (filename or "").lower()
    text = _decode(data)

    if name.endswith(".json") or text.lstrip().startswith(("{", "[")):
        obj = json.loads(text)
        return _parse_json_obj(obj)

    # Default: CSV
    return "csv", _parse_csv(text)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _parse_json_obj(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    # B2B_GESAMT_LEADS.json: {"leads": [...], "je_kampagne": {...}, ...}
    if isinstance(obj, dict) and isinstance(obj.get("leads"), list):
        return "b2b_gesamt", obj["leads"]
    if isinstance(obj, list):
        return "json", obj
    if isinstance(obj, dict):
        return "json", [obj]
    raise ValueError("JSON-Struktur nicht erkannt (erwartet Liste oder {'leads': [...]})")


def _parse_csv(text: str) -> list[dict[str, Any]]:
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for row in reader:
        clean = {(k.strip() if k else k): v for k, v in row.items() if k}
        if any(v not in (None, "") for v in clean.values()):
            rows.append(clean)
    return rows


def dedup_within(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entfernt Duplikate innerhalb eines Imports (nach dedup_key)."""
    seen: set[str] = set()
    out = []
    for r in rows:
        key = r["dedup_key"]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def group_by_campaign(raw_leads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Gruppiert rohe Leads nach Kampagne (für Gesamtbestand-Import)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_leads:
        camp = (
            raw.get("campaign_name")
            or raw.get("kampagne")
            or _campaign_from_fields(raw)
            or "Ohne Kampagne"
        )
        groups.setdefault(str(camp), []).append(raw)
    return groups


def _norm_industry_key(s: str) -> str:
    """Normalisierter Gruppenschlüssel: Groß/Klein, Bindestriche und
    Mehrfach-Leerzeichen vereinheitlichen (merged z.B. 'IT Dienstleister'
    und 'IT-Dienstleister', 'marketing' und 'Marketing')."""
    s = s.strip().lower().replace("-", " ")
    return re.sub(r"\s+", " ", s)


def _industry_raw(raw: dict[str, Any]) -> str:
    return str(raw.get("industry") or raw.get("industry_group") or "").strip()


# Reine Test-/Smoke-Einträge (keine echten Firmen) → werden beim Import verworfen.
_NOISE_SUBSTRINGS = ("smoke", "dummy", "lorem")
# Platzhalter ohne echte Branche → landen gesammelt in „Unklassifiziert".
_UNCLASSIFIED = {"import", "ohne branche", "unbekannt", "unknown", "n/a", "na", "-", ""}
UNCLASSIFIED_LABEL = "Unklassifiziert"


def is_test_noise(raw: dict[str, Any]) -> bool:
    """True für reine Test-/Smoke-Datensätze (z.B. industry '_smoke_')."""
    s = _industry_raw(raw)
    if not s:
        return False
    if s.startswith("_") and s.endswith("_"):  # _smoke_, _test_ …
        return True
    low = s.lower()
    return any(p in low for p in _NOISE_SUBSTRINGS)


def filter_noise(raw_leads: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Entfernt Test-/Smoke-Leads. Gibt (behaltene, anzahl_verworfen) zurück."""
    kept = [r for r in raw_leads if not is_test_noise(r)]
    return kept, len(raw_leads) - len(kept)


def _is_unclassified(label: str) -> bool:
    return label.strip().lower() in _UNCLASSIFIED


def group_by_industry(raw_leads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Gruppiert rohe Leads nach Branche, mit leichter Normalisierung.
    Schreibweise-/Bindestrich-Varianten landen im selben Projekt (häufigste
    Schreibweise = Name); Platzhalter-Branchen werden in „Unklassifiziert" gesammelt."""
    from collections import Counter

    buckets: dict[str, dict[str, Any]] = {}
    for raw in raw_leads:
        ind = _industry_raw(raw) or "Ohne Branche"
        key = _norm_industry_key(ind)
        b = buckets.setdefault(key, {"labels": Counter(), "rows": []})
        b["labels"][ind] += 1
        b["rows"].append(raw)

    groups: dict[str, list[dict[str, Any]]] = {}
    for b in buckets.values():
        label = b["labels"].most_common(1)[0][0]
        if _is_unclassified(label):
            label = UNCLASSIFIED_LABEL
        groups.setdefault(label, []).extend(b["rows"])
    return groups


def _campaign_from_fields(raw: dict[str, Any]) -> str | None:
    ind = raw.get("industry") or raw.get("industry_group")
    city = raw.get("city")
    if ind and city:
        return f"{ind} | {city}"
    return None
