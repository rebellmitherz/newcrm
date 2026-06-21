@echo off
REM ============================================================
REM  CRM oeffnen
REM  Startet den CRM-Server (falls noetig) und oeffnet den Browser
REM  unter http://localhost:8765 . Einfach doppelklicken.
REM ============================================================
cd /d "%~dp0"
title CRM oeffnen

REM Laeuft schon ein Server auf Port 8765?
netstat -ano | findstr ":8765" | findstr /i "LISTENING" >nul
if %errorlevel%==0 (
  echo CRM laeuft bereits - oeffne Browser...
) else (
  echo Starte CRM-Server...
  start "CRM Server" /min "%~dp0.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8765
  echo Warte auf Hochlauf...
  timeout /t 5 /nobreak >nul
)

start "" "http://localhost:8765"
exit /b
