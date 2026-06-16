# Rebellsystem CRM

Eigenständiges, professionelles Lead-CRM. **Komplett getrennt vom KundenAgent/Bot** —
Leads werden nur **importiert** (Einbahnstraße, es wird nie in den KundenAgent zurückgeschrieben).

## Was es kann

- **Projekte/Kampagnen** sauber getrennt verwalten (z.B. „Dachdecker Saarbrücken“, „Marketingagentur Berlin“).
- **Import** aus dem KundenAgent: `leads.csv`, `leads.json` und der Gesamtbestand `B2B_GESAMT_LEADS.json`.
  - Automatische Format-Erkennung, Dedup (E-Mail → Website → Firma+Stadt).
  - Optional: Gesamtbestand automatisch **nach Kampagne in eigene Projekte** aufteilen.
- **Agenda / Wiedervorlage**: pro Lead ein „nächster Schritt“ mit Datum; das Dashboard und die
  Agenda-Ansicht zeigen **überfällig / heute fällig / diese Woche** — so bleibt kein Lead liegen.
  Die Handlungsempfehlung des KundenAgenten (`next_action_label`) wird direkt am Lead angezeigt.
- **Pipeline (Kanban)**: Neu → Kontaktiert → Angebot → Gewonnen / Verloren, per Drag & Drop.
- **Lead-Detail**: alle Felder **editierbar** (Adresse, Kontakt, Grade korrigieren) + **Notizen &
  Aktivitäten** (Anruf, E-Mail, Termin, Wiedervorlage), Verlaufs-Timeline.
- **Dashboard**: Leads gesamt, fällige Wiedervorlagen, Erreichbarkeit, Conversion, Pipeline- &
  Grade-Verteilung, **Duplikat-Prüfung** (gleiche Firma in mehreren Projekten) und **1-Klick-Backup**.
- **Unterwegs-Zugriff**: für Hermes/Sandra (lokaler Datei-Export) **und** fürs Handy (Web-UI im WLAN/per Tunnel).

## Datensicherung

- **Automatisch** beim ersten Upgrade: Kopie unter `crm_backups/`.
- **Per Knopf**: Dashboard → „💾 Backup jetzt“ (sichere Online-Kopie der `crm.db` nach `crm_backups/`).

## Starten

Doppelklick auf **`start.bat`** (richtet beim ersten Mal automatisch alles ein).
Dann im Browser: <http://localhost:8765>

> Voraussetzung: Python 3.11+ ist installiert (ist es bereits).

## Daten

- `crm.db` — die SQLite-Datenbank (Quelle der Wahrheit). Einfach sichern = Datei kopieren.
- `crm_export.json` — read-only Snapshot für Hermes/Sandra (siehe `SANDRA_CRM_ACCESS.md`).

## Unterwegs erreichen

**Variante A – über Hermes/Sandra (empfohlen):** Sandra liest lokal `crm_export.json`.
Details + Beispiel-Task-Card in `SANDRA_CRM_ACCESS.md`.

**Variante B – Web-UI aufs Handy:**
1. PC und Handy im selben WLAN.
2. PC-IP herausfinden: `ipconfig` (z.B. `192.168.1.50`).
3. Am Handy `http://192.168.1.50:8765` öffnen.
4. **Für Zugriff von außerhalb** (mobiles Netz): einen Tunnel nutzen, z.B.
   `cloudflared tunnel --url http://localhost:8765`.

### Zugriffsschutz (für Handy/Tunnel)

Wenn das CRM über das Netz erreichbar ist, **Token setzen** vor dem Start:

```bat
set CRM_TOKEN=dein-geheimes-token
start.bat
```

Dann fragt die Oberfläche beim Öffnen nach dem Token. Ohne gesetzten Token läuft alles offen (rein lokal).

## Aufbau

```
crm/
├─ start.bat            # Start (Windows)
├─ requirements.txt
├─ backend/
│  ├─ main.py           # FastAPI-API + liefert das Web-UI
│  ├─ db.py             # SQLite-Schema
│  ├─ importer.py       # CSV/JSON-Import + Dedup
│  └─ export.py         # crm_export.json für Sandra
├─ frontend/
│  ├─ index.html
│  ├─ style.css
│  └─ app.js
├─ crm.db               # (entsteht beim ersten Start)
└─ crm_export.json      # (entsteht beim ersten Start)
```
