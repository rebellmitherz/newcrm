@echo off
echo.
echo ============================================
echo   CRM: Engine-Import  (neueste Suche - crm.db)
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

:: Engine-Output-Ordner: nimmt automatisch die NEUESTE Suche
:: (signal_leads.json vor hot_leads.json vor leads.json)
set "LATEST=C:\Users\micha\Desktop\KundenAgent\b2bbot\output\latest"
echo.
echo [Import] Suche neueste Leads in:
echo          %LATEST%
echo.
python engine_connector.py --latest-dir "%LATEST%" --db crm.db --area "B2B Agenten System" --mode per_industry

echo.
echo ============================================
echo  Fertig. So siehst du die Leads:
echo   1) start.bat starten (CRM)
echo   2) http://localhost:8765 oeffnen
echo   3) links auf "Leads" - Bereich "B2B Agenten System"
echo   (oben steht "inserted" = neu dazugekommen)
echo ============================================
echo.
pause
