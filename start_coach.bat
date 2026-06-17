@echo off
chcp 65001 > nul
echo.
echo ============================================
echo  ClouseAgent starten (Live Sales Coach)
echo ============================================
echo.

set "CLOUSE=C:\Users\micha\Desktop\ClouseAgent"

if not exist "%CLOUSE%\lead_context.json" (
    echo [Tipp] Noch kein Lead geladen.
    echo        Im CRM einen Lead oeffnen und auf "📞 Coach" klicken.
    echo        Dann start_coach.bat erneut starten.
    echo.
    pause
    exit /b 0
)

echo [Lead] Kontext gefunden:
type "%CLOUSE%\lead_context.json" | python -c "import sys,json; d=json.load(sys.stdin); print('  Firma: '+d.get('company','?')); print('  Branche: '+d.get('industry','?'))" 2>nul
echo.
echo [Start] ClouseAgent wird gestartet...
echo.

pushd "%CLOUSE%"
python app.py
popd
