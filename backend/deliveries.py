"""Lieferungen — Auslieferungs-Schicht des 1k-Produkts.

Eine *Lieferung* ist ein benanntes Lead-Bündel für genau EINEN Kunden, abrufbar
über einen geheimen Token (`/d/<token>`, kein Login). Diese Datei hält die
**reinen, testbaren** Helfer: Token-Erzeugung, die kundenfertige Lead-Karte und
die Kaufbereitschafts-Sicht.

Kaufbereitschaft — Quelle der Wahrheit:
  Neue Signal-Leads tragen die in der KundenAgent-Engine berechneten Felder
  (`kaufbereitschaft_*`) im `raw_json`. Die nutzen wir 1:1. Für ältere Leads (vor
  der Readiness-Schicht) rechnen wir hier einen **Fallback** aus den vorhandenen
  Signal-/Kontaktfeldern — bewusst mit denselben Gewichten wie die Engine
  (`product/bridge/signal_readiness.py`), aber als eigenständige Kopie: das CRM
  importiert KEINEN Engine-Code (FUSION_PLAN-Leitplanke). Deterministisch, kein Netz.
"""
from __future__ import annotations

import csv
import io
import json
import secrets
from typing import Any

# Signaltyp → kundenlesbares Label (Spiegel von signal_discovery.SIGNAL_LABELS).
SIGNAL_LABELS: dict[str, str] = {
    "sales_hiring": "Stellt Vertrieb ein",
    "growth_expansion": "Wächst / baut Team aus",
    "appointment_setter": "Sucht Terminierer / SDR (Outbound)",
    "marketing_hiring": "Investiert in Marketing / Leadgen",
    "leadership_hiring": "Holt Vertriebs-/Marketing-Leitung",
    "new_location": "Eröffnet Standort / expandiert",
}

# Fallback-Scoring (Spiegel der Engine-Gewichte — siehe Modul-Docstring).
_SIGNAL_STAERKE: dict[str, float] = {
    "appointment_setter": 1.0, "sales_hiring": 0.9, "leadership_hiring": 0.8,
    "growth_expansion": 0.65, "marketing_hiring": 0.55, "new_location": 0.55,
}
_W_SIGNAL, _W_FIT, _W_KONTAKT = 0.45, 0.25, 0.30
_GENERISCHE_MAIL_PREFIXES = (
    "info", "kontakt", "mail", "office", "hello", "hallo", "post",
    "contact", "service", "support", "willkommen", "anfrage",
)


def gen_token() -> str:
    """Unrätbarer URL-sicherer Token für den Liefer-Link."""
    return secrets.token_urlsafe(12)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _stufe(score: int) -> str:
    return "hoch" if score >= 70 else ("mittel" if score >= 45 else "niedrig")


def _persoenliche_mail(email: str) -> bool:
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    return email.split("@", 1)[0] not in _GENERISCHE_MAIL_PREFIXES


def _fallback_readiness(raw: dict, email: str, phone: str) -> dict:
    signal_typ = str(raw.get("entdeckt_per_signal") or "").strip().lower()
    s = _SIGNAL_STAERKE.get(signal_typ, 0.5)
    fit = _clamp01(_f(raw.get("signal_fit_score")))
    cq = _clamp01(_f(raw.get("contact_quality_score")) / 100.0)
    has_phone = bool((phone or raw.get("phone") or raw.get("contact_phone") or "").strip())
    pers = _persoenliche_mail(email or raw.get("email") or "")
    kontakt = _clamp01(cq * 0.6 + (0.2 if has_phone else 0.0) + (0.2 if pers else 0.0))
    score = int(round(_clamp01(_W_SIGNAL * s + _W_FIT * fit + _W_KONTAKT * kontakt) * 100))

    gruende: list[str] = []
    if signal_typ:
        gruende.append(f"Kaufsignal: {SIGNAL_LABELS.get(signal_typ, 'zeigt Kaufsignal')}")
    if fit >= 0.7:
        gruende.append(f"Hohe Passung (Fit {fit:.2f})")
    elif fit >= 0.45:
        gruende.append(f"Solide Passung (Fit {fit:.2f})")
    if has_phone and pers:
        gruende.append("Direkt erreichbar: Telefon + persönliche E-Mail")
    elif has_phone:
        gruende.append("Telefon vorhanden — direkt anrufbar")
    elif pers:
        gruende.append("Persönliche E-Mail-Adresse")
    return {
        "score": score, "stufe": _stufe(score), "gruende": gruende[:4],
        "beleg_url": str(raw.get("signal_quelle_url") or "").strip(),
        "quelle": "fallback",
    }


def readiness_view(raw: dict, *, email: str = "", phone: str = "") -> dict:
    """Kaufbereitschafts-Sicht eines Leads: Engine-Wert wenn vorhanden, sonst Fallback.

    Rückgabe: {score:int, stufe:str, gruende:list[str], beleg_url:str, quelle:str}
    """
    if not isinstance(raw, dict):
        raw = {}
    if raw.get("kaufbereitschaft_score") is not None:
        score = int(round(_f(raw.get("kaufbereitschaft_score"))))
        gr = raw.get("kaufbereitschaft_gruende")
        gruende = [str(g) for g in gr][:4] if isinstance(gr, list) else []
        stufe = str(raw.get("kaufbereitschaft_stufe") or "").strip().lower() or _stufe(score)
        return {
            "score": max(0, min(100, score)),
            "stufe": stufe,
            "gruende": gruende,
            "beleg_url": str(raw.get("kaufbereitschaft_beleg_url")
                             or raw.get("signal_quelle_url") or "").strip(),
            "quelle": "engine",
        }
    return _fallback_readiness(raw, email, phone)


def _parse_raw(raw_json: Any) -> dict:
    if isinstance(raw_json, dict):
        return raw_json
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            obj = json.loads(raw_json)
            return obj if isinstance(obj, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def build_card(lead_row: dict) -> dict:
    """Bildet eine CRM-Lead-Zeile (inkl. `raw_json`) auf die kundenfertige Karte ab.

    Bewusst nur Verkaufs-relevante Felder — KEINE internen IDs, Stage, dedup_key,
    kein roher raw_json. Kontaktdaten kommen aus den (geputzten) CRM-Spalten,
    Signal-/Kaufbereitschaft aus `raw_json`.
    """
    raw = _parse_raw(lead_row.get("raw_json"))
    email = (lead_row.get("email") or raw.get("email") or "").strip()
    phone = (lead_row.get("phone") or raw.get("phone") or raw.get("contact_phone") or "").strip()
    signal_typ = str(raw.get("entdeckt_per_signal") or "").strip().lower()
    r = readiness_view(raw, email=email, phone=phone)
    return {
        "firma": (lead_row.get("company_name") or "").strip(),
        "ansprechpartner": (lead_row.get("contact_name") or "").strip(),
        "email": email,
        "telefon": phone,
        "website": (lead_row.get("website") or "").strip(),
        "ort": (lead_row.get("city") or raw.get("city") or "").strip(),
        "signal": signal_typ,
        "signal_label": SIGNAL_LABELS.get(signal_typ, ""),
        "signal_titel": str(raw.get("signal_titel") or "").strip(),
        "kaufbereitschaft_score": r["score"],
        "kaufbereitschaft_stufe": r["stufe"],
        "kaufbereitschaft_gruende": r["gruende"],
        "beleg_url": r["beleg_url"],
    }


_CSV_COLS = [
    ("firma", "Firma"), ("ansprechpartner", "Ansprechpartner"), ("email", "E-Mail"),
    ("telefon", "Telefon"), ("website", "Website"), ("ort", "Ort"),
    ("signal_label", "Kaufsignal"), ("signal_titel", "Signal-Beleg"),
    ("kaufbereitschaft_stufe", "Kaufbereitschaft"), ("kaufbereitschaft_score", "Score"),
    ("beleg_url", "Beleg-Link"),
]


def cards_to_csv(cards: list[dict]) -> str:
    """Lieferung als CSV (für den Export-Button auf der Kundenseite)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([label for _, label in _CSV_COLS])
    for c in cards:
        w.writerow([c.get(key, "") for key, _ in _CSV_COLS])
    return buf.getvalue()
