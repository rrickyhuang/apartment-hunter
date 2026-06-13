@echo off
REM Launches the Apartment Hunter web UI bound to all interfaces so phones
REM and other devices on the same Wi-Fi can reach it at http://<PC-LAN-IP>:5000.
REM Requires a one-time Windows Firewall rule (see README).
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:5000
python -m apartment_hunter.web --host 0.0.0.0
