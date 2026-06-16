@echo off
REM ============================================================
REM  EINMALIGE Einrichtung des festen Tunnels  crm.rebellsystem.com
REM  Voraussetzung: Subdomain crm ist bei Cloudflare schon "Active"
REM  (Cloudflare-Account + NS-Eintrag bei IONOS erledigt).
REM ============================================================
setlocal
cd /d %~dp0
set HOSTNAME=crm.rebellsystem.com
set TUNNEL=crm

REM --- cloudflared sicherstellen ---
if not exist cloudflared.exe (
  echo [Setup] Lade cloudflared von Cloudflare herunter ^(einmalig^)...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
)

echo.
echo [1/3] Gleich oeffnet sich der Browser. Bei Cloudflare einloggen und
echo       die Zone  crm.rebellsystem.com  AUTORISIEREN (Button "Authorize").
echo.
pause
cloudflared.exe tunnel login

echo.
echo [2/3] Erstelle den Tunnel "%TUNNEL%"...
cloudflared.exe tunnel create %TUNNEL%

echo.
echo [3/3] Verknuepfe %HOSTNAME% mit dem Tunnel (DNS-Eintrag)...
cloudflared.exe tunnel route dns %TUNNEL% %HOSTNAME%

echo.
echo ============================================================
echo   FERTIG. Ab jetzt taeglich starten mit:  start_crm_tunnel.bat
echo   Feste Adresse:  https://%HOSTNAME%
echo ============================================================
pause
