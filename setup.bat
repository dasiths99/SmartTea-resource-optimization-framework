@echo off
rem ======================================================================
rem  SmartTea-LK C04 - one-time setup on a new Windows PC
rem
rem  Installs (only what is missing):
rem    Python 3.14, Java 25 (Temurin), Node.js LTS, MongoDB   - via winget
rem    Maven 3.9.9                                              - official Apache zip, checksum verified
rem  Then prepares the project:
rem    .venv + Python packages (exact versions: requirements-lock.txt)
rem    dashboard packages (frontend), backend build (backend)
rem    trained models (artifacts/ is not in git, so they are rebuilt here)
rem    data checksum check + tests
rem
rem  Run it once from the project folder (double-click). Windows may ask for
rem  administrator permission while installing; click Yes.
rem  Run it again any time to repair or update: finished steps are skipped,
rem  the backend is rebuilt clean. "setup.bat retrain" also retrains the models.
rem  Afterwards start the system with start.bat.
rem ======================================================================
setlocal EnableExtensions
cd /d "%~dp0"
title SmartTea setup
set "MVN_VER=3.9.9"
set "MVN_DIR=%USERPROFILE%\tools\apache-maven-%MVN_VER%"
set "WG=--exact --silent --accept-package-agreements --accept-source-agreements"
set "RETRAIN="
if /i "%~1"=="retrain" set "RETRAIN=1"

echo.
echo  SmartTea-LK C04 setup
echo  =====================
echo.

where winget >nul 2>&1
if errorlevel 1 (
    echo [ERROR] winget is not available. Install "App Installer" from the Microsoft Store, then run setup.bat again.
    goto :fail
)
call :refreshpath

rem ---------------------------------------------------------------- 0. running?
rem  A running dashboard or backend locks its files (npm ci and the backend build would fail).
set "INUSE="
for %%P in (8000 8080 5173) do (
    netstat -ano | findstr /r /c:":%%P .*LISTENING" >nul && set "INUSE=%%P"
)
if defined INUSE (
    echo [0/10] SmartTea is running ^(port %INUSE%^) - stopping it with stop.bat first ...
    call "%~dp0stop.bat"
    cd /d "%~dp0"
)

rem ---------------------------------------------------------------- 1. Python
echo [1/10] Python 3.14
call :findpython
if not defined PY (
    echo       installing Python 3.14 ...
    winget install --id Python.Python.3.14 %WG%
    call :refreshpath
    call :findpython
)
if not defined PY (
    echo [ERROR] Python 3.14 was not found after installing. Restart the PC and run setup.bat again.
    goto :fail
)
echo       OK: %PY%

rem ---------------------------------------------------------------- 2. Java
echo [2/10] Java 25
call :findjava
if not defined JDK (
    echo       installing Eclipse Temurin JDK 25 ...
    winget install --id EclipseAdoptium.Temurin.25.JDK %WG%
    call :findjava
)
if not defined JDK (
    echo [ERROR] Java 25 was not found after installing.
    goto :fail
)
set "JAVA_HOME=%JDK%"
setx JAVA_HOME "%JDK%" >nul
echo       OK: %JDK%

rem ---------------------------------------------------------------- 3. Node.js
echo [3/10] Node.js
call :refreshpath
where npm >nul 2>&1
if errorlevel 1 (
    echo       installing Node.js LTS ...
    winget install --id OpenJS.NodeJS.LTS %WG%
    call :refreshpath
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js / npm was not found after installing. Restart the PC and run setup.bat again.
    goto :fail
)
echo       OK: npm found

rem ---------------------------------------------------------------- 4. MongoDB
echo [4/10] MongoDB
sc query MongoDB >nul 2>&1
if errorlevel 1 (
    echo       installing MongoDB Community Server ...
    winget install --id MongoDB.Server %WG%
)
sc query MongoDB >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The MongoDB service was not found after installing.
    goto :fail
)
sc query MongoDB | find "RUNNING" >nul
if errorlevel 1 net start MongoDB >nul 2>&1
sc query MongoDB | find "RUNNING" >nul
if errorlevel 1 (
    echo [ERROR] MongoDB is installed but not running. Right-click setup.bat, "Run as administrator".
    goto :fail
)
echo       OK: MongoDB service running

rem ---------------------------------------------------------------- 5. Maven
echo [5/10] Maven %MVN_VER%
if not exist "%MVN_DIR%\bin\mvn.cmd" (
    echo       downloading Maven %MVN_VER% from archive.apache.org and checking its SHA-512 ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $v='%MVN_VER%'; $tools=Join-Path $env:USERPROFILE 'tools'; New-Item -ItemType Directory -Force $tools | Out-Null; $zip=Join-Path $env:TEMP ('apache-maven-'+$v+'-bin.zip'); $u='https://archive.apache.org/dist/maven/maven-3/'+$v+'/binaries/apache-maven-'+$v+'-bin.zip'; Invoke-WebRequest $u -OutFile $zip -UseBasicParsing; $exp=((Invoke-WebRequest ($u+'.sha512') -UseBasicParsing).Content -split '\s+')[0].Trim().ToLower(); $act=(Get-FileHash $zip -Algorithm SHA512).Hash.ToLower(); if ($exp -ne $act) { throw 'Maven checksum mismatch' }; Expand-Archive $zip -DestinationPath $tools -Force; Remove-Item $zip"
)
if not exist "%MVN_DIR%\bin\mvn.cmd" (
    echo [ERROR] Maven could not be installed. Check the internet connection and run setup.bat again.
    goto :fail
)
powershell -NoProfile -Command "$m='%MVN_DIR%\bin'; $p=[Environment]::GetEnvironmentVariable('Path','User'); if (-not $p) { $p='' }; if ($p -notlike ('*'+$m+'*')) { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';')+';'+$m).TrimStart(';'), 'User') }"
call :refreshpath
set "PATH=%JAVA_HOME%\bin;%MVN_DIR%\bin;%PATH%"
echo       OK: %MVN_DIR%

rem ---------------------------------------------------------------- 6. Python packages
echo [6/10] Python virtual environment and packages (a few minutes)
if not exist ".venv\Scripts\python.exe" "%PY%" -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Could not create the .venv folder.
    goto :fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
set "REQ=requirements-lock.txt"
if not exist "%REQ%" set "REQ=requirements.txt"
".venv\Scripts\python.exe" -m pip install -r "%REQ%"
if errorlevel 1 (
    echo [ERROR] Installing the Python packages failed. See the messages above.
    goto :fail
)
".venv\Scripts\python.exe" -m ipykernel install --user --name smarttea --display-name "SmartTea (.venv)" >nul 2>&1
echo       OK: packages from %REQ%, notebook kernel "SmartTea (.venv)"

rem ---------------------------------------------------------------- 7. Dashboard + backend
echo [7/10] Dashboard packages and backend build (first time downloads libraries)
pushd frontend
if exist package-lock.json (call npm ci) else (call npm install)
if errorlevel 1 (
    popd
    echo [ERROR] npm could not install the dashboard packages.
    goto :fail
)
popd
pushd backend
rem clean = never run a stale old build (the cause of "Method Not Allowed" after a code change)
call mvn -q -DskipTests clean package
if errorlevel 1 (
    popd
    echo [ERROR] The backend build failed. See the messages above.
    goto :fail
)
popd
echo       OK: dashboard and backend ready

rem ---------------------------------------------------------------- 8. Models
echo [8/10] Trained models
if defined RETRAIN (
    echo       "retrain" given: the models are trained again
    del /q "artifacts\models\yield_catboost.*" "artifacts\models\runoff_xgboost.*" "artifacts\models\soil_n_response.json" 2>nul
)
if exist "artifacts\models\yield_catboost.joblib" if exist "artifacts\models\runoff_xgboost.joblib" goto :models_ok
echo       training and comparing the models - about 10 minutes ...
".venv\Scripts\python.exe" -m src.models.compare_models
if errorlevel 1 (
    echo [ERROR] Model training failed.
    goto :fail
)
:models_ok
if not exist "artifacts\models\soil_n_response.json" ".venv\Scripts\python.exe" -m src.optimizer.soil_n
if not exist "artifacts\models\soil_n_response.json" (
    echo [ERROR] The soil-N response model could not be fitted.
    goto :fail
)
echo       OK: artifacts\models (yield_catboost, runoff_xgboost, soil_n_response)

rem ---------------------------------------------------------------- 9. ML service can load everything
echo [9/10] ML service check (loads the models and data exactly as the service does)
".venv\Scripts\python.exe" -c "from src.optimizer.optimize import Surrogates; from src.api.live import BlockStore; s = Surrogates(); BlockStore(); print('      OK: yield', s.meta['yield']['model'], 'test R2', s.meta['yield']['scores']['test_r2'], '| runoff', s.meta['runoff']['model'], 'test R2', s.meta['runoff']['scores']['test_r2'])"
if errorlevel 1 (
    echo [ERROR] The ML service could not load the models. Run "setup.bat retrain".
    goto :fail
)

rem ---------------------------------------------------------------- 9. Checks
echo [10/10] Data checksums and tests
".venv\Scripts\python.exe" -m src.data.check_data
".venv\Scripts\python.exe" -m pytest tests -q
if errorlevel 1 (
    echo [WARNING] Some tests failed. The system may still start; see the messages above.
)

echo.
echo  =====================================================
echo   Setup finished.
echo   Start: start.bat    Stop: stop.bat
echo   Dashboard: http://localhost:5173
echo  =====================================================
echo.
choice /c YN /n /m "Start SmartTea now? [Y/N] "
if errorlevel 2 exit /b 0
call "%~dp0start.bat"
exit /b 0

rem ======================================================================
rem  helpers
rem ======================================================================
:findpython
set "PY="
for %%C in ("%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%ProgramFiles%\Python314\python.exe" "C:\Python314\python.exe") do (
    if not defined PY if exist "%%~C" set "PY=%%~C"
)
if defined PY exit /b 0
for /f "delims=" %%P in ('py -3.14 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
exit /b 0

:findjava
set "JDK="
for /d %%D in ("%ProgramFiles%\Eclipse Adoptium\jdk-25*") do set "JDK=%%~fD"
exit /b 0

:refreshpath
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%P"
exit /b 0

:fail
echo.
echo Setup stopped. Fix the problem above and run setup.bat again (finished steps are skipped).
pause
exit /b 1
