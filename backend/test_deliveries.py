"""Tests für die Lieferungs-Logik (backend/deliveries.py) — deterministisch.

Standalone:  python -m backend.test_deliveries   (vom crm-Root)
"""
from __future__ import annotations

import json

from backend import deliveries as d


def test_gen_token_unrätbar_und_eindeutig():
    a, b = d.gen_token(), d.gen_token()
    assert a != b
    assert len(a) >= 12 and "/" not in a and "+" not in a   # url-safe


def test_readiness_engine_wert_gewinnt():
    raw = {"kaufbereitschaft_score": 92, "kaufbereitschaft_stufe": "hoch",
           "kaufbereitschaft_gruende": ["Kaufsignal: stellt Vertrieb ein"],
           "kaufbereitschaft_beleg_url": "https://stepstone.de/j1",
           "signal_fit_score": 0.1}   # darf NICHT überschreiben
    r = d.readiness_view(raw, email="a@x.de", phone="+49")
    assert r["score"] == 92 and r["stufe"] == "hoch" and r["quelle"] == "engine"
    assert r["beleg_url"] == "https://stepstone.de/j1"


def test_readiness_fallback_rechnet():
    raw = {"entdeckt_per_signal": "sales_hiring", "signal_fit_score": 0.6,
           "contact_quality_score": 50, "signal_quelle_url": "https://x/j"}
    r = d.readiness_view(raw, email="max.muster@x.de", phone="+4955")
    # 0.45*0.9 + 0.25*0.6 + 0.30*(0.5*0.6+0.2+0.2) = 0.765 → 76 (hoch)
    assert r["score"] == 76 and r["stufe"] == "hoch" and r["quelle"] == "fallback"
    assert any("Kaufsignal" in g for g in r["gruende"])
    assert r["beleg_url"] == "https://x/j"


def test_readiness_fallback_schwach_ist_niedrig():
    raw = {"entdeckt_per_signal": "marketing_hiring", "signal_fit_score": 0.2,
           "contact_quality_score": 10}
    r = d.readiness_view(raw, email="info@x.de", phone="")
    assert r["stufe"] == "niedrig" and r["quelle"] == "fallback"


def test_persoenliche_mail():
    assert d._persoenliche_mail("anna.b@x.de") is True
    assert d._persoenliche_mail("info@x.de") is False
    assert d._persoenliche_mail("") is False


def test_build_card_mappt_und_strippt():
    raw = {"entdeckt_per_signal": "appointment_setter", "signal_titel": "SDR (m/w/d)",
           "signal_quelle_url": "https://stepstone.de/j",
           "kaufbereitschaft_score": 88, "kaufbereitschaft_stufe": "hoch",
           "kaufbereitschaft_gruende": ["Kaufsignal: sucht SDR"],
           "kaufbereitschaft_beleg_url": "https://stepstone.de/j"}
    lead_row = {"id": 7, "company_name": "X GmbH", "contact_name": "Anna",
                "email": "anna@x.de", "phone": "+4955", "website": "https://x.de",
                "city": "Köln", "stage": "new", "dedup_key": "email:anna@x.de",
                "raw_json": json.dumps(raw)}
    c = d.build_card(lead_row)
    assert c["firma"] == "X GmbH" and c["ort"] == "Köln"
    assert c["signal_label"] == "Sucht Terminierer / SDR (Outbound)"
    assert c["kaufbereitschaft_score"] == 88 and c["kaufbereitschaft_stufe"] == "hoch"
    assert c["beleg_url"] == "https://stepstone.de/j"
    # KEINE internen Felder durchsickern lassen
    for verboten in ("raw_json", "id", "stage", "dedup_key"):
        assert verboten not in c


def test_build_card_defensiv_ohne_raw():
    c = d.build_card({"company_name": "Y", "raw_json": "kein json{"})
    assert c["firma"] == "Y"
    assert 0 <= c["kaufbereitschaft_score"] <= 100
    assert c["signal_label"] == ""   # kein Signal → leer


def test_cards_to_csv():
    cards = [d.build_card({"company_name": "A GmbH", "email": "a@a.de",
                           "raw_json": json.dumps({"entdeckt_per_signal": "sales_hiring",
                                                   "kaufbereitschaft_score": 80,
                                                   "kaufbereitschaft_stufe": "hoch"})})]
    csv_text = d.cards_to_csv(cards)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("Firma;Ansprechpartner;E-Mail")
    assert "A GmbH" in lines[1] and "hoch" in lines[1]


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS {fn.__name__}"); ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"== {ok}/{len(fns)} grün ==")
    return ok == len(fns)


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run_all() else 1)
