@echo off
echo.
echo ============================================
echo   CRM: Engine-Import  hot_leads.json - crm.db
echo ============================================
echo.

:: Backup mit Zeitstempel
set "TS=%date:~6,4%-%date:~3,2%-%date:~0,2%_%time:~0,2%-%time:~3,2%"
set "TS=%TS: =0%"
set "BACKUP=crm_backups\pre_engine_%TS%.db"
if not exist crm_backups mkdir crm_backups
copy crm.db "%BACKUP%" > nul 2>&1
if %errorlevel%==0 (
    echo [Backup] %BACKUP%
) else (
    echo [Info] Kein Backup noetig - crm.db existiert noch nicht
)

:: Engine-Ausgabe importieren
set "ENGINE=C:\Users\micha\Desktop\KundenAgent\b2bbot\output\latest\hot_leads.json"
echo.
echo [Import] %ENGINE%
echo.
python engine_connector.py "%ENGINE%" --db crm.db --area "B2B Agenten System" --mode per_industry

echo.
echo [Fertig] CRM auf http://localhost:8765 oeffnen und F5 druecken.
echo.
pause
