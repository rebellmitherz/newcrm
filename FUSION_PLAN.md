# Fusions-Plan: CRM + KundenAgent + ClouseAgent → ein vermietbares System

> **Zweck:** Bauplan, wie das saubere CRM (dieses Projekt) als Kundenportal in die
> bestehende Multi-Mandanten-Produktschicht des KundenAgent eingesetzt wird, und
> wie der ClouseAgent als Live-Call-Coach andockt — ohne Engine oder Closer zu verändern.
>
> **Status:** Plan. In diesem Dokument wird **nichts** am Code geändert.
> **Ziel:** 3.000 €/Monat wiederkehrend mit einer Handvoll Kunden.
> **Erstellt:** 2026-06-16

---

## 0. Das Bild in einem Satz

Leads finden (KundenAgent-Engine) → landen automatisch im aufgeräumten CRM des Kunden →
Kunde arbeitet sie über Pipeline/Agenda ab → klickt „Anrufen" → ClouseAgent coacht live →
Ergebnis + nächste Wiedervorlage schreiben sich zurück ins CRM. Alles human-gated.

```
Kunde ──Login──▶  CRM (= Kundenportal, das schöne UI)
                    │  Auftrag in normaler Sprache
                    ▼
            OPERATOR ──▶ BRIDGE ──▶ ENGINE (b2bbot, UNBERÜHRT)
                    │                    │  output/latest/hot_leads.json
                    ▼                    ▼
            CRM-Pipeline  ◀── CONNECTOR (JSON → CRM-Import) ──┘
                    │  „Anrufen"
                    ▼
            ClouseAgent (Live-Coach) ──▶ Zusammenfassung ──▶ zurück in CRM-Timeline
```

---

## 1. Unverrückbare Leitplanken (aus `product/STRATEGIE.md`, gelten weiter)

1. **Engine (`b2bbot/`) und Closer (`ClouseAgent/`) bleiben read-only.** Zugriff nur über die Bridge bzw. einen Adapter. Kein Refactor, keine Logik entfernen.
2. **Kein Auto-Send.** Mailversand/Approve/Follow-up bleiben ein hartes menschliches Tor.
   - **Wichtig:** Leads in das **eigene CRM des Kunden** zu schreiben ist **kein** „Send" — das ist nur Befüllen seines eigenen Postfachs. Das darf automatisch laufen. Versendet wird erst nach Freigabe.
3. **Harte Mandanten-Isolation.** Jeder Kunde = eigener Datenraum. Keine zwei Kunden teilen Daten/DB/Engine.
4. **Kunde sieht nie** Engine-Code, Admin-Cockpit, SMTP/Token/Setup-Felder.
5. **Secrets nie committen.** (Siehe Sofort-Hinweis unten.)

---

## 1b. Rechts-/Produkt-Leitplanke: **Signal-first** (NEU 2026-06-16)

**Das ist die verteidigbarste UND kommerziell beste Linie — beides zugleich.**

**Warum (rechtlich):** Kalte B2B-Mail in DE braucht „mutmaßliche Einwilligung" (§7 UWG) —
ein **Pro-Empfänger-Test**: Hat *diese* Firma plausibles Interesse an *diesem* Angebot?
Ein **Kaufsignal ist genau dieser Beweis.** Breite Branchensuche („alle Handwerker in NRW")
liefert ihn nicht; Signal-Targeting schon. Auto-/Massen-Spray kann den Test bauartbedingt
nicht erfüllen → falsche Seite.

**Default des Produkts:**
- **Signal-basierte Suche ist der Standard- und Aushängeschild-Pfad** (`b2bbot` Signal-Targeting
  + `{aufhaenger}`-Personalisierung). Breite Branchensuche bleibt vorhanden, ist aber **nicht** das
  Verkaufsversprechen.
- **Human-Gate bleibt** (kein Auto-Send) — der Klick ist der Moment, in dem die Pro-Empfänger-
  Beurteilung stattfindet, und verschiebt die Verantwortung zum Kunden, der seinen Markt kennt.

**Kunden-Versprechen v1 (so formulieren, nicht „Massen-Kaltmail"):**
> „Wir finden Firmen mit **konkretem Kaufsignal** für dein Angebot, schreiben eine **passende,
> persönliche** Erstansprache — du gibst sie frei und arbeitest sie im CRM mit Live-Coach ab."

**Pflicht-Hygiene (Stärke skaliert damit):** enge Signal↔Angebot-Kopplung · echte Personalisierung
am Signal · geringe Menge statt Masse · einfacher Opt-out · korrektes Impressum/Absender-Identität ·
B2B-Adressen (Rolle/Firma) · DSGVO: Rechtsgrundlage berechtigtes Interesse (Art. 6 (1) f) +
Info-/Auskunfts-/Lösch-Logik · vorhandene `do_not_contact`/Bounce-/Deliverability-Mechanik nutzen.

**Wichtig:** Signal erhöht die Plausibilität, ist **kein** garantierter „safe harbor". Vor dem
ersten Kunden **einmal anwaltlich §7 UWG / DSGVO bestätigen** lassen. (Kein Anwaltsersatz.)

**Glücksfall:** Signal-first ist genau das, was die Engine **schon am besten kann** und was die
**höchsten Antwortquoten** bringt. Rechtlich sicherste = kommerziell beste Linie.

---

## 2. Wo das CRM andockt: die F8-Lücke

`product/STRATEGIE.md` stellt **F8 — „Echtes Kunden-Frontend + Connector"** bewusst zurück
(„erfordert zuerst Produkt-/Vertriebsentscheidung + Design-Vorschlag"). Heute füllt diese
Lücke nur die Platzhalter-Mini-UI (`product/ui/kunden_dashboard.html`, 4 einfache Ansichten).

**Entscheidung dieses Plans:** Das CRM ist die reife Umsetzung von F8. Die Mini-UI wird
durch das CRM ersetzt (oder das CRM läuft neben ihr und übernimmt die Kundensicht).
Nichts Neues erfinden — Vorhandenes verbinden.

---

## 3. Was schon steht (Fundament) vs. was zu bauen ist

| Baustein | Datei(en) | Stand |
|---|---|---|
| Mandanten-Isolation (eigenes `data_dir` je Kunde) | `product/platform/mandant.py` | ✅ fertig |
| Plattform-Orchestrierung (Runner+Bridge je Mandant) | `product/platform/plattform.py` | ✅ fertig |
| Login + Sessions je Kunde | `product/auth/sessions.py` | ✅ fertig |
| Lizenz-/Feature-System | `product/licensing/` | ✅ fertig |
| Bridge als einzige Engine-Leitung | `product/bridge/engine_bridge.py` | ✅ fertig |
| Engine liefert fertige Lead-Listen | `b2bbot/output/latest/hot_leads.json`, `hot_handoffs.json/.csv` | ✅ vorhanden |
| CRM importiert CSV/JSON mit Auto-Spaltenerkennung | `backend/importer.py`, `/api/import` | ✅ fertig |
| **① Connector: Engine-Ausgabe → CRM je Mandant** | neu: `product/bridge/crm_connector.py` | 🔶 ~80 % da |
| **② CRM mehrmandantenfähig + Portal-Login** | `backend/main.py` + `product/auth` | 🔶 zu verdrahten |
| **③ ClouseAgent als „Anrufen"-Aktion + Rückschreiben** | `product/closer/closer_adapter.py`, `frontend/app.js` | 🔶 Adapter füllen |

Die „echte Arbeit" sind **drei Verbindungsstücke**, kein Neubau.

---

## 4. Verbindungsstück ① — Connector (Engine → CRM)

**Das wertvollste, risikoärmste Stück. Zuerst bauen — es macht den Kreislauf sichtbar.**

### Glücksfall: das Daten-Mapping ist fast geschenkt
Das CRM erkennt Spalten über `FIELD_ALIASES` (`backend/importer.py`) — und die Aliase
**decken die Engine-Feldnamen bereits ab**:

| CRM-Zielfeld | Engine-Felder (schon als Alias erkannt) |
|---|---|
| `company_name` | `company_name`, `canonical_company_name` |
| `contact_name` | `contact_full_name`, `managing_director` |
| `email` / `phone` | `email` / `phone` |
| `website` | `website`, `source_url` |
| `city` | `city`, `city_detected` |
| `industry` | `industry`, `industry_group` |
| `grade` | `lead_status`, `lead_class` |
| `score` | `contact_quality_score`, `revenue_fit_score` |
| `next_action_label` | `next_action_label`, `next_action` (die Empfehlung!) |

→ Die Engine-Ausgabe passt fast 1:1 ins CRM. Kaum Mapping-Aufwand.

### Aufbau
- **Neu:** `product/bridge/crm_connector.py` (in der Produktschicht, **nicht** in `b2bbot/`).
- Nach einem bestätigten Lauf liest er `<mandant-data_dir>/output/latest/hot_leads.json`
  (bzw. `hot_handoffs.csv`) und **ruft die vorhandene CRM-Import-API** dieses Mandanten auf
  (`POST /api/import`, mit dem Mandanten-Token). Kein Direktzugriff auf die DB nötig.
- **Read-only zur Engine:** liest nur Ausgabedateien. Das bestehende `b2bbot/modules/crm_push.py`
  (Pipedrive) bleibt **unangetastet** — es wird schlicht **nicht** benutzt. Wir ersetzen den
  externen Pipedrive-Push durch das eigene CRM (kein Pipedrive-Abo, eigene Daten, besseres UI).

### Akzeptanzkriterium
Ein Testlauf der Engine erzeugt `hot_leads.json` → Connector läuft → die Leads erscheinen
im CRM des richtigen Mandanten, korrekt einsortiert, mit `next_action_label` als Empfehlung.
**Keine** Dubletten (CRM-Dedup greift bereits).

### Nicht anfassen
`b2bbot/modules/*`, `mine.py`, Engine-Pipelines. Nur lesen.

---

## 5. Verbindungsstück ② — CRM mehrmandantenfähig + Portal-Login

### Empfohlener v1-Ansatz: eine CRM-Instanz pro Mandant
Konsequent zur Isolations-Philosophie (`mandant.py`: jeder Mandant hat eigenes `data_dir`):
- Jeder Mandant bekommt eine **eigene** `crm.db` in seinem isolierten Verzeichnis
  (`product/data/<mandant>/crm.db`).
- Kein Mehrmandanten-Refactor des CRM-Datenmodells nötig → **niedrigstes Risiko**,
  perfekte Trennung, schnell startklar.
- Nachteil (später optimierbar): mehrere CRM-Prozesse. Für eine Handvoll Kunden irrelevant.

> Alternative B (1 CRM-Prozess, `tenant_id`-Spalte auf jeder Zeile, gefilterte Queries):
> effizienter bei vielen Kunden, aber größerer Umbau + höheres Isolations-Risiko.
> **Erst später**, wenn Kundenzahl es verlangt.

### Login
- Authentifizierung läuft über das **vorhandene** `product/auth/sessions.py`
  (`mandant_verifizieren`, `session_erstellen`, `session_pruefen`).
- Der Kunde meldet sich am Portal an; die Plattform leitet ihn auf seine CRM-Instanz
  und injiziert deren **mandantenspezifischen** Token.
- **Kleine CRM-Änderung:** `require_token` (heute ein geteilter `CRM_TOKEN`) bleibt, aber
  der Token ist **pro Mandant** und wird von der Plattform gesetzt — kein global geteiltes Geheimnis mehr.

### Ports (festhalten, sonst Kollision)
- `8765` = b2bbot **Admin-Cockpit** (intern) **und** heutiges lokales CRM — kollidiert!
- `8766` = `product/ui/server.py` (heutige Mini-UI).
- **Regel:** Im gehosteten Betrieb bekommt jede CRM-Instanz einen eigenen Port (oder läuft
  hinter einem Reverse-Proxy je Mandant-Subdomain). Lokales 8765 ist nur Entwicklung.

### Akzeptanzkriterium
Zwei Test-Mandanten anlegen → jeder loggt sich ein → jeder sieht **ausschließlich** seine
eigenen Leads. Kein Datenüberlapp.

---

## 6. Verbindungsstück ③ — ClouseAgent als „Anrufen"-Aktion

### Andockpunkt
`product/closer/closer_adapter.py` (`CloserAdapter`) ist die in der SPEC vorgesehene Naht
(„Closer = Nachbar, kein Mitbewohner"). ClouseAgent selbst bleibt unverändert.

### Ablauf
1. In der CRM-Lead-Karte (`frontend/app.js`, `openLead`) ein Button **„📞 Anrufen"**.
2. Klick → Adapter startet ClouseAgent **mit Lead-Kontext** (Firma, Branche, Notizen,
   passendes `playbook.json`).
3. ClouseAgent coacht live (Transcript + sales_brain), wie heute.
4. Nach dem Call schreibt ClouseAgent eine **Zusammenfassung** in eine Ausgabedatei.
5. Der Connector (aus §4) liest sie und legt im CRM-Lead an: Timeline-Eintrag (`call`/`note`),
   setzt `next_action_date` + `next_action_label`, ggf. Stage-Wechsel.

→ ClouseAgent bleibt „Nachbar": er produziert nur eine Ausgabe, das CRM zieht sie sich.

### Akzeptanzkriterium
Aus einer Lead-Karte „Anrufen" → ClouseAgent öffnet mit den richtigen Daten → nach Abschluss
steht im CRM-Lead automatisch ein Gesprächseintrag + Wiedervorlage.

---

## 7. Reihenfolge / Meilensteine

| Phase | Inhalt | Ergebnis |
|---|---|---|
| **A — v1-Versprechen festlegen** (kein Code, 5 Min) | Was wird dem Kunden garantiert (ohne Auto-Send zu versprechen) | Klares, ehrliches Angebot |
| **B — Connector ①** | Engine-Ausgabe → CRM je Mandant | Der Kreislauf wird sichtbar; größter Aha-Effekt |
| **C — Multi-Mandant + Login ②** | CRM-Instanz je Mandant + `product/auth` | Echtes „vermietbar", saubere Trennung |
| **D — ClouseAgent-Hook ③** | „Anrufen" + Rückschreiben | Das „Komplett-Ding" steht |
| **E — Hosten + Stabil + DSGVO** | 24/7-Server (kein PC nötig), Zuverlässigkeits-Pass auf dem Kernpfad, Zustellbarkeit/AV-Vertrag | Verkaufbar |
| **F — 1 Pilotkunde → Preis → Skalieren** | Pilot (ggf. vergünstigt) → Beweis → 500–1.000 €/Kunde | Weg zu 3k |

**Korrektur (Michael, 2026-06-16):**
- **LinkedIn-Bot bleibt unangetastet liegen** — NICHT löschen (Engine ist read-only), NICHT im
  Verkauf featuren, solange er schlecht läuft. Der Kunde sieht Engine-Interna ohnehin nie (Black Box
  hinter der Bridge). Stört niemanden, vermeidet späteres Durcheinander.
- **KEIN „eine Stadt/Branche"-Produkt-Limit.** Die Engine ist branchen-/städteübergreifend — das ist
  ihre Stärke (STRATEGIE.md: „branchenunabhängige Plattform"). Der enge Fokus war nur als **Test-Fokus**
  für den Stabilitäts-Pass (Phase E) gemeint und wird an der Branche/Stadt des **ersten Pilotkunden**
  gemacht — kein künstliches Limit. Damit entfällt das frühere „Trimmen" in Phase A.

---

## 8. Rechnung zum 3k-Ziel

Eigene Positionierung (`b2bbot/POSITIONING.md`): ersetzt 600–3.000 €/Monat an VA/SDR/Apollo.
→ **500–1.000 €/Kunde/Monat** sauber begründbar.

- 3 Kunden × 1.000 € = **3.000 €** ✅
- 6 Kunden × 500 € = **3.000 €** ✅

Erreichbar mit einer **Handvoll** Kunden, nicht Hunderten.

---

## 9. Risiken & Gegenmaßnahmen

| Risiko | Maßnahme |
|---|---|
| Scraping/Suche bricht → unzuverlässige Lieferung | Phase E: Zuverlässigkeits-Pass, erst 1 Branche/Stadt stabil |
| DSGVO bei Kaltakquise-Mail (DE heikel) | Human-Gate bleibt; AV-Vertrag; Opt-out/Impressum-Logik der Engine nutzen |
| Datenleck zwischen Mandanten | v1 = physisch getrennte DB je Mandant (§5) |
| Abhängigkeit von deinem PC | Phase E: echtes Hosting |
| LinkedIn-Bot zieht Qualität runter | Aus v1-Angebot streichen |

---

## 10. ⚠️ Sofort-Hinweis (Sicherheit)

In `product/product_config.json` steht ein **echter Telegram-Bot-Token im Klartext**
(`bot_token: 8917528510:AAF…`), obwohl die eigene Regel „keine echten Keys" lautet.
**Falls dieser Ordner je in einem Git-Repo war/ist: Token neu erzeugen** (BotFather → revoke)
und künftig nur über eine gitignorierte Datei laden. (In diesem Plan wird nichts geändert.)

---

## 11. Was in KEINER Phase angefasst wird

- `b2bbot/` Engine-Kern (`mine.py`, `cae`, `modules/*`) — nur über Bridge/Connector lesen.
- `ClouseAgent/` — nur über Adapter, produziert Ausgabe, wird gezogen.
- Hermes Prime / OpenClaw / Sandra — nie referenzieren/kopieren.
- Keine Sende-/Approve-/Reply-Logik einschränken. Kein Auto-Send.

---

## 12. Nächster konkreter Schritt (wenn du grün gibst)

**Phase B, Connector ①** zuerst — kleinster Eingriff, größter sichtbarer Effekt:
einen Engine-Testlauf nehmen und seine `hot_leads.json` durch den neuen Connector ins
CRM eines Test-Mandanten fließen lassen. Sobald du die Engine-Leads im schönen CRM siehst,
ist der Rest „nur noch" Verdrahtung in der hier festgelegten Reihenfolge.
