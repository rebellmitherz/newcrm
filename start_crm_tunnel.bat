@echo off
REM ============================================================
REM  Rebellsystem CRM - fester Link  https://crm.rebellsystem.com
REM  Taeglicher Start. Voraussetzung: setup_crm_tunnel.bat lief einmal.
REM ============================================================
setlocal
cd /d %~dp0
set HOSTNAME=crm.rebellsystem.com
set TUNNEL=crm

REM --- Token laden (einmalig erzeugt, bleibt gleich) ---
if not exist share_token.txt (
  powershell -NoProfile -Command "[guid]::NewGuid().ToString('N') | Out-File -Encoding ascii -NoNewline share_token.txt"
)
set /p CRM_TOKEN=<share_token.txt

REM --- Python-Umgebung + Abhaengigkeiten ---
if not exist .venv (
  echo [Setup] Erstelle virtuelle Umgebung...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [Setup] Pruefe Abhaengigkeiten...
pip install -q -r requirements.txt

REM --- CRM-Server in eigenem Fenster (nur lokal) ---
start "CRM Server - NICHT schliessen" cmd /c ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765"
timeout /t 4 /nobreak >nul

cls
echo ============================================================
echo   CRM ist erreichbar unter:
echo.
echo        https://%HOSTNAME%
echo.
echo   Token (zusammen mit dem Link weitergeben):
echo        %CRM_TOKEN%
echo.
echo   Fenster offen lassen. Beenden = dieses + das Server-Fenster schliessen.
echo ============================================================
echo.
cloudflared.exe tunnel run --url http://localhost:8765 %TUNNEL%
pause
