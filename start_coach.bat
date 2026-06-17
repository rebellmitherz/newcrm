@echo off
echo.
echo ============================================
echo   ClouseAgent starten - Live Sales Coach
echo ============================================
echo.

set "CLOUSE=C:\Users\micha\Desktop\ClouseAgent"

if not exist "%CLOUSE%\lead_context.json" (
    echo [Tipp] Noch kein Lead geladen.
    echo        Im CRM einen Lead oeffnen und auf "Coach" klicken.
    echo        Dann diese Datei erneut starten.
    echo.
    pause
    exit /b 0
)

echo [Lead] Kontext gefunden - ClouseAgent kennt jetzt die Firma.
echo.
echo [Start] ClouseAgent wird gestartet...
echo.

pushd "%CLOUSE%"
python app.py
popd
