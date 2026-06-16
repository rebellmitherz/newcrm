# CRM-Zugriff für Hermes / Sandra (read-only)

Damit Michael unterwegs Lead-Fragen beantwortet bekommt, **ohne** dass das CRM
an den KundenAgent/Bot gekoppelt ist.

## Prinzip

- Quelle der Wahrheit ist `C:\Users\micha\Desktop\crm\crm.db` (SQLite).
- Das CRM schreibt bei **jeder Änderung** automatisch einen read-only Snapshot:
  `C:\Users\micha\Desktop\crm\crm_export.json`
- **Sandra/OpenClaw liest nur diese JSON-Datei.** Niemals schreiben. Keine Bot-Kopplung.

## Erlaubte Quelle (nur diese)

* `C:\Users\micha\Desktop\crm\crm_export.json`

## Struktur von `crm_export.json`

```json
{
  "generated_at": "2026-06-15T...",
  "totals": {
    "projekte": 5,
    "leads_gesamt": 1665,
    "mit_email": 1401,
    "mit_telefon": 1198,
    "nach_phase": { "new": 1600, "contacted": 40, "offer": 15, "won": 6, "lost": 4 },
    "wiedervorlage_ueberfaellig": 7,
    "wiedervorlage_heute": 3
  },
  "projekte": [ { "id": 1, "name": "Dachdecker | Saarbrücken", "source": "...", "leads": 39 } ],
  "leads": [
    { "id": 12, "project_id": 1, "company_name": "...", "contact_name": "...",
      "email": "...", "phone": "...", "city": "...", "industry": "...",
      "score": 100, "grade": "A-Lead", "temperature": "hot", "stage": "new",
      "next_action_label": "Erstkontakt anrufen", "next_action_date": "2026-06-18" }
  ]
}
```

## Pflichtregeln (analog B2B-Grounding)

1. Konkrete Lead-Zahlen/Firmen nur nennen, wenn `generated_at` frisch ist und zur Frage passt.
2. Quelle + Zeitpunkt immer angeben:
   - **QUELLE:** `crm_export.json`
   - **ZEITPUNKT:** Wert aus `generated_at`
   - **VERIFIZIERUNGSSTATUS:** VERIFIZIERT (read-only gelesen)
3. Keine erfundenen Leads/Scores. Wenn Datei fehlt oder leer: klar sagen
   „CRM-Export leer/fehlt — Michael muss das CRM einmal starten/importieren.“
4. Sandra ändert **nichts** im CRM. Statuswechsel/Notizen macht Michael in der Web-Oberfläche.

## Beispiel-Task-Card (Hermes → Sandra)

```
ZIEL: Aktuelle Top-Leads aus dem CRM read-only liefern.
ARBEITSMODUS: read-only
QUELLE: C:\Users\micha\Desktop\crm\crm_export.json
VERBOTEN: schreiben, CRM-DB anfassen, Bot/KundenAgent berühren
OUTPUT:
  QUELLE:
  ZEITPUNKT (generated_at):
  PROJEKTE (Name + Lead-Anzahl):
  TOP-LEADS (Firma · Kontakt · E-Mail · Telefon · Score · Grade · Phase):
  PHASEN-VERTEILUNG:
```
