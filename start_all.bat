@echo off
chcp 65001 >nul
title Vision Civic - Unified Launcher
cd /d "%~dp0"

echo ========================================================
echo         🚀 STARTING VISION CIVIC FULL STACK
echo ========================================================
echo.
echo [1/2] Starting FastAPI Backend on http://127.0.0.1:8000 ...
start "Vision Civic - Backend" cmd /k "cd Backend && .\venv\Scripts\python.exe app.py"

timeout /t 2 /nobreak >nul

echo [2/2] Starting Vite Frontend on http://localhost:5173 ...
start "Vision Civic - Frontend" cmd /k "cd Frontend && npm run dev"

echo.
echo ========================================================
echo  ✅ Backend and Frontend have been launched!
echo.
echo  • Frontend UI: http://localhost:5173
echo  • Backend Docs: http://127.0.0.1:8000/docs
echo.
echo  To run the CivicSense AI Vision Engine (Pothole/Fire/Waste):
echo   - You can launch it directly from the Frontend Live Monitoring page
echo   - OR run Pothole\start_integrated_mode.bat in another terminal
echo ========================================================
echo.
pause
