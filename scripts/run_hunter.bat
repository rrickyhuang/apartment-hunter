@echo off
REM Apartment Hunter — invoked by Windows Task Scheduler.
REM Logs appended to logs\run.log so you can inspect missed runs.

cd /d "C:\Users\Ricky\Documents\CodingProjects\apartment hunter"

if not exist logs mkdir logs

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [%date% %time%] failed to activate venv >> logs\run.log
    exit /b 1
)

echo. >> logs\run.log
echo === [%date% %time%] starting run === >> logs\run.log
python -m apartment_hunter.run --once >> logs\run.log 2>&1
echo === [%date% %time%] exit=%errorlevel% === >> logs\run.log
