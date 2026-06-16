@echo off
REM ============================================================
REM  Rebellsystem CRM - TEILEN (oeffentlicher Link)
REM  Doppelklick: startet das CRM + einen Tunnel und zeigt
REM  eine https-Adresse, die du an andere weitergeben kannst.
REM  Die andere Person muss NICHTS installieren - nur Link + Token.
REM ============================================================
setlocal enabledelayedexpansion
cd /d %~dp0

REM --- 1) Token: einmalig erzeugen, lokal speichern, wiederverwenden ---
if not exist share_token.txt (
  powershell -NoProfile -Command "[guid]::NewGuid().ToString('N') | Out-File -Encoding ascii -NoNewline share_token.txt"
)
set /p CRM_TOKEN=<share_token.txt

REM --- 2) cloudflared sicherstellen (einmaliger Download, ~50 MB) ---
if not exist cloudflared.exe (
  echo [Setup] Lade cloudflared von Cloudflare herunter ^(einmalig^)...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
)

REM --- 3) Python-Umgebung + Abhaengigkeiten ---
if not exist .venv (
  echo [Setup] Erstelle virtuelle Umgebung...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [Setup] Pruefe Abhaengigkeiten...
pip install -q -r requirements.txt

REM --- 4) CRM-Server in eigenem Fenster starten (nur lokal, Tunnel reicht) ---
start "CRM Server - NICHT schliessen" cmd /c ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765"

REM kurz warten, bis der Server hochgefahren ist
timeout /t 4 /nobreak >nul

cls
echo ============================================================
echo    CRM TEILEN
echo ============================================================
echo.
echo    TOKEN (zusammen mit dem Link weitergeben):
echo.
echo        !CRM_TOKEN!
echo.
echo    Gleich erscheint unten eine Adresse wie:
echo        https://....trycloudflare.com
echo.
echo    Diese Adresse + den Token an die Person schicken.
echo    Sie oeffnet den Link im Browser, gibt den Token ein - fertig.
echo.
echo    Solange dieses Fenster offen bleibt, ist die Seite erreichbar.
echo    Beenden: dieses Fenster schliessen (Server-Fenster auch).
echo ============================================================
echo.

REM --- 5) Tunnel starten - die oeffentliche URL erscheint hier ---
cloudflared.exe tunnel --url http://localhost:8765
pause
