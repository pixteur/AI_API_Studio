@echo off
title Nano Banana Studio
echo.
echo   Nano Banana Studio 1.0 beta
echo   ============================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found.
    echo   Download Python 3.11 from https://python.org/downloads
    echo   Make sure to check "Add python.exe to PATH" during install.
    echo.
    pause
    exit /b 1
)

:: Launch the app
python nbs.py

:: Keep window open if it crashes
if errorlevel 1 (
    echo.
    echo   The app exited with an error. See above for details.
    pause
)
