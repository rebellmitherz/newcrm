@echo off
REM ============================================================
REM  Rebellsystem CRM - fester Link ueber ngrok
REM  Taeglicher Start per Doppelklick.
REM  Voraussetzung (einmalig): ngrok_token.txt + ngrok_domain.txt
REM  mit deinen Daten aus dem ngrok-Dashboard gefuellt.
REM ============================================================
setlocal enabledelayedexpansion
cd /d %~dp0

REM --- 1) Pruefen, ob die zwei kleinen Konfig-Dateien existieren ---
if not exist ngrok_token.txt (
  echo.
  echo [FEHLER] Datei ngrok_token.txt fehlt.
  echo   Oeffne dein ngrok-Dashboard, kopiere deinen Authtoken und
  echo   speichere ihn in die Datei  ngrok_token.txt  in diesem Ordner.
  echo.
  pause
  exit /b 1
)
if not exist ngrok_domain.txt (
  echo.
  echo [FEHLER] Datei ngrok_domain.txt fehlt.
  echo   Trage deine feste ngrok-Domain hinein, z.B.:
  echo        dein-name.ngrok-free.app
  echo.
  pause
  exit /b 1
)
set /p NGROK_TOKEN=<ngrok_token.txt
set /p NGROK_DOMAIN=<ngrok_domain.txt

REM --- 2) Token: einmalig erzeugen, lokal speichern, wiederverwenden ---
if not exist share_token.txt (
  powershell -NoProfile -Command "[guid]::NewGuid().ToString('N') | Out-File -Encoding ascii -NoNewline share_token.txt"
)
set /p CRM_TOKEN=<share_token.txt

REM --- 3) ngrok sicherstellen (einmaliger Download + Entpacken) ---
if not exist ngrok.exe (
  echo [Setup] Lade ngrok herunter ^(einmalig^)...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip' -OutFile 'ngrok.zip'"
  echo [Setup] Entpacke ngrok...
  powershell -NoProfile -Command "Expand-Archive -Path 'ngrok.zip' -DestinationPath '.' -Force"
  del ngrok.zip
)

REM --- 4) Authtoken bei ngrok hinterlegen (idempotent) ---
ngrok.exe config add-authtoken %NGROK_TOKEN%

REM --- 5) Python-Umgebung + Abhaengigkeiten ---
if not exist .venv (
  echo [Setup] Erstelle virtuelle Umgebung...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [Setup] Pruefe Abhaengigkeiten...
pip install -q -r requirements.txt

REM --- 6) CRM-Server in eigenem Fenster (nur lokal) ---
start "CRM Server - NICHT schliessen" cmd /c ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765"
timeout /t 4 /nobreak >nul

cls
echo ============================================================
echo   CRM ist erreichbar unter:
echo.
echo        https://%NGROK_DOMAIN%
echo.
echo   Token ^(zusammen mit dem Link weitergeben^):
echo        %CRM_TOKEN%
echo.
echo   Fenster offen lassen. Beenden = dieses + das Server-Fenster
echo   schliessen.
echo ============================================================
echo.
ngrok.exe http 8765 --url=https://%NGROK_DOMAIN%
pause
