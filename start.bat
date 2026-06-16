@echo off
REM ============================================================
REM  Rebellsystem CRM - Start
REM  Doppelklick startet das CRM unter http://localhost:8765
REM ============================================================
cd /d %~dp0

if not exist .venv (
  echo [Setup] Erstelle virtuelle Umgebung...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [Setup] Pruefe Abhaengigkeiten...
pip install -q -r requirements.txt

REM Optionaler Schutz fuer Handy-/Tunnel-Zugriff:
REM   set CRM_TOKEN=meingeheimestoken   (vor dem Start setzen)

echo.
echo ============================================================
echo   CRM laeuft:  http://localhost:8765
echo   Im selben WLAN vom Handy:  http://DEINE-PC-IP:8765
echo   (PC-IP findest du mit:  ipconfig )
echo   Beenden: dieses Fenster schliessen oder STRG+C
echo ============================================================
echo.

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8765
pause
