@echo off
REM CEO Briefing — Windows Scheduled Task Wrapper (Silver Tier Capstone)
REM Schedule: Sunday at 11:00 PM

set VAULT_DIR=D:\AI_Employee_Vault
set LOG_FILE=%VAULT_DIR%\Logs\cron-briefing.log

echo === CEO Briefing Run: %date% %time% === >> "%LOG_FILE%"

cd /d "%VAULT_DIR%"

REM Run the Daily Briefing Python script first for data collection
python "%VAULT_DIR%\Skills\Daily_Briefing\daily_briefing.py" >> "%LOG_FILE%" 2>&1

REM Invoke Claude Code with the CEO Briefing skill
claude -p "Run the ceo-briefing skill for this week. Read Business_Goals.md, scan /Done/ for completed tasks and /Logs/ for activity data. Generate the weekly CEO briefing and save it to /Briefings/" >> "%LOG_FILE%" 2>&1

echo === Completed: %date% %time% === >> "%LOG_FILE%"
