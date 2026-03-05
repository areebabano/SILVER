@echo off
REM Daily Briefing — Windows Scheduled Task Wrapper (Silver Tier)
REM Schedule: Weekdays at 8:00 AM

set VAULT_DIR=D:\AI_Employee_Vault
set SCRIPT=%VAULT_DIR%\Skills\Daily_Briefing\daily_briefing.py
set LOG_FILE=%VAULT_DIR%\Logs\cron-daily.log

echo === Daily Briefing Run: %date% %time% === >> "%LOG_FILE%"

cd /d "%VAULT_DIR%"

if exist "%SCRIPT%" (
    python "%SCRIPT%" >> "%LOG_FILE%" 2>&1
    echo === Completed: %date% %time% === >> "%LOG_FILE%"
) else (
    echo ERROR: Script not found: %SCRIPT% >> "%LOG_FILE%"
    exit /b 1
)
