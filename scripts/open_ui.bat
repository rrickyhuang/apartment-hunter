@echo off
REM Launches the Apartment Hunter web UI bound to all interfaces so phones
REM and other devices on the same Wi-Fi can reach it at http://<PC-LAN-IP>:5000.
REM Requires a one-time Windows Firewall rule (see README).
cd /d "C:\Users\Ricky\Documents\CodingProjects\apartment hunter"
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:5000
python -m apartment_hunter.web --host 0.0.0.0
