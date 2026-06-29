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
_GENERISCHE_MAIL_PREFIXES = {
    "info", "kontakt", "contact", "mail", "email", "mails", "office", "buero", "bureau",
    "hello", "hallo", "moin", "post", "service", "support", "willkommen", "welcome",
    "anfrage", "anfragen", "kundenservice", "kundendienst", "vertrieb", "sales",
    "team", "zentrale", "empfang", "reception", "sekretariat", "verwaltung",
    "buchhaltung", "rechnung", "rechnungen", "finance", "finanzen", "accounting",
    "einkauf", "bestellung", "bestellungen", "order", "shop", "verkauf", "beratung",
    "presse", "press", "media", "marketing", "werbung", "pr",
    "jobs", "job", "karriere", "career", "careers", "bewerbung", "bewerbungen",
    "recruiting", "hr", "personal", "datenschutz", "dsgvo", "privacy", "impressum",
    "webmaster", "admin", "noreply", "donotreply", "newsletter", "news",
    "abo", "praxis", "kanzlei", "termin", "termine", "anmeldung", "reservierung",
    "reservation", "booking", "billing", "invoice", "feedback", "kontaktformular",
}


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


def _local_tokens(local: str) -> list[str]:
    for sep in ".-_+":
        local = local.replace(sep, " ")
    for d in "0123456789":
        local = local.replace(d, " ")
    return [t for t in local.split() if t]


def _persoenliche_mail(email: str, contact_name: str = "") -> bool:
    """True NUR, wenn die Adresse plausibel einen Personennamen trägt — info@,
    kontakt@, vertrieb@, info.berlin@ … gelten NIE als persönlich (konservativ,
    sonst verliert die Lieferung beim Kunden Glaubwürdigkeit)."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    local = email.split("@", 1)[0].strip()
    toks = _local_tokens(local)
    if not toks:
        return False
    if local in _GENERISCHE_MAIL_PREFIXES or any(t in _GENERISCHE_MAIL_PREFIXES for t in toks):
        return False
    name = (contact_name or "").lower()
    for ch in ".,-_/\\":
        name = name.replace(ch, " ")
    nt = [t for t in name.split() if len(t) >= 3]
    if nt and any(t in toks for t in nt):
        return True
    alpha = [t for t in toks if t.isalpha() and len(t) >= 2]
    return len(alpha) >= 2


def _ist_mobilnummer(phone: str) -> bool:
    """Dt. Mobilfunk (015x/016x/017x bzw. +4915…) — eher Direktkontakt als Zentrale."""
    p = (phone or "").strip()
    if not p:
        return False
    digits = "".join(c for c in p if c.isdigit())
    if p.lstrip().startswith("+"):
        if digits.startswith("49"):
            digits = digits[2:]
        else:
            return False
    elif digits.startswith("0049"):
        digits = digits[4:]
    digits = digits.lstrip("0")
    return digits.startswith(("15", "16", "17"))


def _fallback_readiness(raw: dict, email: str, phone: str) -> dict:
    signal_typ = str(raw.get("entdeckt_per_signal") or "").strip().lower()
    s = _SIGNAL_STAERKE.get(signal_typ, 0.5)
    fit = _clamp01(_f(raw.get("signal_fit_score")))
    cq = _clamp01(_f(raw.get("contact_quality_score")) / 100.0)
    tel_roh = (phone or raw.get("phone") or raw.get("contact_phone") or "").strip()
    has_phone = bool(tel_roh)
    name = raw.get("contact_full_name") or raw.get("managing_director") or raw.get("contact_person") or ""
    pers = _persoenliche_mail(email or raw.get("email") or "", name)
    kontakt = _clamp01(cq * 0.6 + (0.2 if has_phone else 0.0) + (0.2 if pers else 0.0))
    score = int(round(_clamp01(_W_SIGNAL * s + _W_FIT * fit + _W_KONTAKT * kontakt) * 100))

    gruende: list[str] = []
    if signal_typ:
        gruende.append(f"Kaufsignal: {SIGNAL_LABELS.get(signal_typ, 'zeigt Kaufsignal')}")
    if fit >= 0.7:
        gruende.append(f"Hohe Passung (Fit {fit:.2f})")
    elif fit >= 0.45:
        gruende.append(f"Solide Passung (Fit {fit:.2f})")
    tel_label = "Mobilnummer (Direktkontakt)" if _ist_mobilnummer(tel_roh) else "Telefonnummer vorhanden"
    if has_phone and pers:
        gruende.append(f"{tel_label} + persönliche E-Mail")
    elif has_phone:
        gruende.append(tel_label)
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


def _frische_text(tage: Any) -> str:
    """Kundenlesbares Frische-Label aus dem Anzeigenalter (Tage). '' wenn unbekannt.

    Eigenständige Mini-Variante (CRM-Repo hängt nicht an der KundenAgent-Engine).
    Bevorzugt wird ohnehin das von der Engine mitgelieferte `signal_frische_text`."""
    if not isinstance(tage, int):
        return ""
    if tage <= 0:
        return "heute"
    if tage == 1:
        return "gestern"
    if tage < 7:
        return f"vor {tage} Tagen"
    if tage < 14:
        return "vor 1 Woche"
    if tage < 31:
        return f"vor {tage // 7} Wochen"
    if tage < 61:
        return "vor 1 Monat"
    if tage < 365:
        return f"vor {max(1, tage // 30)} Monaten"
    return "über 1 Jahr"


# Portal-Domain → kundenlesbarer Quellenname (Beleg-Vertrauen auf der Lieferseite).
_QUELLEN_NAMEN: list[tuple[str, str]] = [
    ("stepstone.", "Stepstone"), ("indeed.", "Indeed"), ("linkedin.", "LinkedIn"),
    ("xing.", "Xing"), ("yourfirm.", "Yourfirm"), ("stellenanzeigen.", "Stellenanzeigen.de"),
    ("kimeta.", "Kimeta"), ("jobvector.", "Jobvector"), ("meinestadt.", "meinestadt"),
    ("jobware.", "Jobware"), ("monster.", "Monster"), ("personio.", "Personio"),
    ("join.com", "Join"), ("lever.co", "Lever"), ("greenhouse.", "Greenhouse"),
    ("karriere.", "karriere.at"), ("jobs.ch", "jobs.ch"),
]


def _quelle_name(url: str) -> str:
    """Kundenlesbarer Name der Beleg-Quelle aus der URL (Portal). Fallback: die Domain."""
    u = (url or "").strip().lower()
    if not u:
        return ""
    for marker, name in _QUELLEN_NAMEN:
        if marker in u:
            return name
    # Fallback: blanke Domain (ohne www./Protokoll)
    rest = u.split("//", 1)[-1].split("/", 1)[0]
    return rest[4:] if rest.startswith("www.") else rest


def _belege_bauen(raw: dict, signal_typ: str) -> list[dict]:
    """Nachprüfbare Beleg-Liste je Lead — pro Signal eine Quelle (Portal + Link +
    Frische). Nutzt `signal_belege` (Stapelung) wenn vorhanden, sonst das
    Einzel-Signal aus `signal_titel`/`signal_quelle_url`. Das ist der Wert-Beweis,
    den der Käufer anklicken kann."""
    roh = raw.get("signal_belege")
    out: list[dict] = []
    if isinstance(roh, list) and roh:
        for b in roh:
            if not isinstance(b, dict):
                continue
            st = str(b.get("signal_typ") or "").strip().lower()
            url = str(b.get("quelle_url") or "").strip()
            alter = b.get("alter_tage")
            out.append({
                "signal_label": SIGNAL_LABELS.get(st, b.get("signal_label") or st),
                "titel": str(b.get("titel") or "").strip(),
                "quelle_name": _quelle_name(url),
                "quelle_url": url,
                "frische": _frische_text(alter if isinstance(alter, int) else None),
            })
    else:
        url = str(raw.get("signal_quelle_url") or "").strip()
        if signal_typ or url:
            alter = raw.get("signal_alter_tage")
            out.append({
                "signal_label": SIGNAL_LABELS.get(signal_typ, ""),
                "titel": str(raw.get("signal_titel") or "").strip(),
                "quelle_name": _quelle_name(url),
                "quelle_url": url,
                "frische": _frische_text(alter if isinstance(alter, int) else None),
            })
    return out


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


def ist_auslieferbar(lead_row: dict) -> bool:
    """Liefer-Tor (FUSION-konform, kein Engine-Import): ein Lead darf NUR in eine
    Kunden-Lieferung, wenn er das KundenAgent-Premium-Gate als PREMIUM passiert hat.
    Die Engine schreibt das Urteil als ``premium_klasse`` ins ``raw_json``. Fehlt es
    oder ist es != 'PREMIUM' (None/REVIEW/REJECT), lief der Lead am Gate vorbei (z. B.
    Klassik-b2bbot) → NICHT ausliefern. (Schließt den 20:21-Vorfall.)"""
    raw = _parse_raw(lead_row.get("raw_json"))
    pk = str(raw.get("premium_klasse") or lead_row.get("premium_klasse") or "").strip().upper()
    return pk == "PREMIUM"


def nur_auslieferbare(lead_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Teilt CRM-Lead-Zeilen in (auslieferbar, blockiert). Blockiert = nicht PREMIUM.
    Aufruf-Punkt: Lieferungs-Erstellung in ``main.py`` — vor dem Schreiben der
    delivery_leads die blockierten herausnehmen; bleibt 0 übrig → Lieferung verweigern."""
    ok: list[dict] = []
    blocked: list[dict] = []
    for r in lead_rows:
        (ok if ist_auslieferbar(r) else blocked).append(r)
    return ok, blocked


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
    alter = raw.get("signal_alter_tage")
    alter = alter if isinstance(alter, int) else None
    frische = str(raw.get("signal_frische_text") or "").strip() or _frische_text(alter)
    # Signal-Stapelung: alle Signale der Firma + lesbare Labels (Heißgrad-Beweis).
    roh_sig = raw.get("signale")
    signale = [str(s).strip().lower() for s in roh_sig if str(s).strip()] if isinstance(roh_sig, list) else []
    if not signale and signal_typ:
        signale = [signal_typ]
    signale = list(dict.fromkeys(signale))
    signale_labels = [SIGNAL_LABELS.get(s, s) for s in signale]
    belege = _belege_bauen(raw, signal_typ)
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
        "signal_alter_tage": alter,
        "signal_frische": frische,
        "signale_labels": signale_labels,
        "signale_text": " + ".join(signale_labels),
        "signal_count": len(signale),
        "belege": belege,
        "quellen_text": ", ".join(dict.fromkeys(b["quelle_name"] for b in belege if b["quelle_name"])),
        "kaufbereitschaft_score": r["score"],
        "kaufbereitschaft_stufe": r["stufe"],
        "kaufbereitschaft_gruende": r["gruende"],
        "beleg_url": r["beleg_url"],
        "briefing": raw.get("briefing") or {"kurzprofil": "", "opener": "", "einwaende": []},
        "linkedin_profil": raw.get("linkedin_profil") or {},
        "aufhaenger": str(raw.get("aufhaenger") or "").strip(),
    }


_CSV_COLS = [
    ("firma", "Firma"), ("ansprechpartner", "Ansprechpartner"), ("email", "E-Mail"),
    ("telefon", "Telefon"), ("website", "Website"), ("ort", "Ort"),
    ("signale_text", "Kaufsignale"), ("signal_titel", "Signal-Beleg"),
    ("quellen_text", "Quelle(n)"), ("signal_frische", "Signal-Frische"),
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
