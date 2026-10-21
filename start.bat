@echo off
rem ============================================================
rem  SmartTea-LK C04 - start everything
rem    1. Python ML service  (FastAPI)     http://localhost:8000
rem    2. Backend            (Spring Boot) http://localhost:8080
rem    3. Dashboard          (React)       http://localhost:5173
rem  Each part runs in its own window. Use stop.bat to close them.
rem ============================================================
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0."
title SmartTea launcher

rem ---- already running? (a second start would fail and the OLD version would keep answering) ----
set "INUSE="
for %%P in (8000 8080 5173) do (
    netstat -ano | findstr /r /c:":%%P .*LISTENING" >nul && set "INUSE=%%P"
)
if defined INUSE (
    echo SmartTea seems to be running already: port %INUSE% is in use.
    echo Run stop.bat first, then start.bat again - this also loads any code changes.
    goto :fail
)

rem ---- Java and Maven (installed for this project) ----
if not defined JAVA_HOME for /d %%D in ("%ProgramFiles%\Eclipse Adoptium\jdk-25*") do set "JAVA_HOME=%%~fD"
set "PATH=%JAVA_HOME%\bin;%USERPROFILE%\tools\apache-maven-3.9.9\bin;%PATH%"

rem ---- checks (setup.bat prepares all of these on a new PC) ----
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found: .venv
    echo         On a new PC, run setup.bat first.
    goto :fail
)
if not exist "artifacts\models\yield_catboost.joblib" (
    echo [ERROR] Trained models not found in artifacts\models. Run setup.bat first.
    goto :fail
)
where java >nul 2>&1 || (echo [ERROR] Java not found. Install Java 25 or set JAVA_HOME. & goto :fail)
where mvn  >nul 2>&1 || (echo [ERROR] Maven not found. Expected in %USERPROFILE%\tools\apache-maven-3.9.9 & goto :fail)
where npm  >nul 2>&1 || (echo [ERROR] Node.js / npm not found. Install Node.js. & goto :fail)

rem ---- MongoDB (Windows service) ----
sc query MongoDB | find "RUNNING" >nul
if errorlevel 1 (
    echo MongoDB is not running - trying to start it...
    net start MongoDB >nul 2>&1
    sc query MongoDB | find "RUNNING" >nul
    if errorlevel 1 (
        echo [ERROR] Could not start MongoDB. Right-click start.bat and choose "Run as administrator",
        echo         or start the "MongoDB" service in Windows Services.
        goto :fail
    )
)
echo MongoDB ............ running

rem ---- dashboard packages (first run only) ----
if not exist "frontend\node_modules" (
    echo Installing dashboard packages - first run only, this can take a few minutes...
    pushd frontend
    call npm install
    popd
)

rem ---- start the three parts ----
echo Starting ML service .. port 8000
start "SmartTea ML service (8000)" /d "%ROOT%" cmd /k ".venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000"

echo Starting backend ..... port 8080 (first start downloads libraries, can take a few minutes)
start "SmartTea backend (8080)" /d "%ROOT%\backend" cmd /k "mvn spring-boot:run"

echo Starting dashboard ... port 5173
start "SmartTea dashboard (5173)" /d "%ROOT%\frontend" cmd /k "npm run dev -- --port 5173"

rem ---- wait for the backend, then open the dashboard ----
echo.
echo Waiting for the backend to be ready...
set /a TRIES=0
:wait
curl -s -o nul http://localhost:8080/api/status && goto :ready
set /a TRIES+=1
if %TRIES% geq 100 goto :slow
timeout /t 3 /nobreak >nul
goto :wait

:ready
echo.
echo All parts are running. Opening the dashboard: http://localhost:5173
start "" http://localhost:5173
echo You can close this window. Run stop.bat to stop everything.
timeout /t 10 >nul
exit /b 0

:slow
echo.
echo The backend is taking longer than 5 minutes. Check the "SmartTea backend" window for errors.
echo When it shows "Started SmartTeaApplication", open http://localhost:5173
pause
exit /b 1

:fail
echo.
pause
exit /b 1
