@echo off
title OTT Platform Backend API
echo =============================================
echo   OTT Platform Backend - Starting Server
echo =============================================

REM Check virtual environment
if exist .venv\Scripts\python.exe (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [*] Applying database migrations...
%PYTHON% -m alembic upgrade head

echo.
echo =============================================
echo   API is live at: http://localhost:8000
echo   Swagger Docs at: http://localhost:8000/api/v1/docs
echo =============================================
echo Press Ctrl + C to stop the server.
echo.

%PYTHON% -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause
