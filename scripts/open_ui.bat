@echo off
REM Launches the Apartment Hunter web UI in your default browser.
cd /d "C:\Users\Ricky\Documents\CodingProjects\apartment hunter"
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:5000
python -m apartment_hunter.web
