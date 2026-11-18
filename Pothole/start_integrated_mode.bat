@echo off
chcp 65001 >nul
title CivicSense Unified AI System
cd /d "%~dp0"

echo ======================================================
echo    Starting CivicSense Integrated Mode (3 AI Models)
echo ======================================================
echo.
echo 1. Live Webcam Feed (ESP32: 192.168.206.33)
echo 2. Sample Road Video (ESP32: 192.168.206.33)
echo 3. Sample Road Video (Offline / No ESP32)
echo 4. Run Simulated ESP32 Hardware Server
echo 5. Sample Road Video + Simulated ESP32 (Local Testing)
echo.
set /p choice="Enter choice [1, 2, 3, 4, or 5] (Default is 2): "

if "%choice%"=="1" (
    echo Starting with Live Webcam and ESP32 at 192.168.206.33...
    .\.venv\Scripts\python.exe civicsense_all_in_one.py --source 0 --esp-ip 192.168.206.33
) else if "%choice%"=="3" (
    echo Starting with Sample Video in Offline Mode...
    .\.venv\Scripts\python.exe civicsense_all_in_one.py --source "Watch Video_ Terrible potholes in Rangoon Road.mp4" --no-esp
) else if "%choice%"=="4" (
    echo Starting Simulated ESP32 Hardware Server...
    .\.venv\Scripts\python.exe mock_esp32.py 8088
) else if "%choice%"=="5" (
    echo Starting Simulated ESP32 and Sample Video...
    start "CivicSense ESP32 Hardware Simulator" cmd /k ".\.venv\Scripts\python.exe mock_esp32.py 8088"
    timeout /t 2 /nobreak >nul
    .\.venv\Scripts\python.exe civicsense_all_in_one.py --source "Watch Video_ Terrible potholes in Rangoon Road.mp4" --esp-ip 127.0.0.1:8088
) else (
    echo Starting with Sample Video and ESP32 at 192.168.206.33...
    .\.venv\Scripts\python.exe civicsense_all_in_one.py --source "Watch Video_ Terrible potholes in Rangoon Road.mp4" --esp-ip 192.168.206.33
)

pause
