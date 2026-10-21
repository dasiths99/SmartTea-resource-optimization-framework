@echo off
rem ============================================================
rem  SmartTea-LK C04 - stop everything started by start.bat
rem  Closes the ML service (8000), backend (8080) and dashboard (5173):
rem  for each port it finds the listening process, walks up to the window
rem  start.bat opened for it (uvicorn / spring-boot:run / npm run dev) and
rem  closes that whole process tree. MongoDB (a Windows service) keeps running.
rem ============================================================
setlocal
title SmartTea stop

powershell -NoProfile -ExecutionPolicy Bypass -Command "$marks = 'uvicorn src.api.main','spring-boot:run','SmartTeaApplication','npm run dev','run dev','vite'; foreach ($port in 8000,8080,5173) { $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $c) { Write-Host ('port ' + $port + ': not running'); continue }; $id = [int]$c.OwningProcess; $top = $id; for ($i = 0; $i -lt 8; $i++) { $w = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $id); if (-not $w) { break }; $par = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $w.ParentProcessId); if (-not $par) { break }; $cl = [string]$par.CommandLine; $hit = $false; foreach ($m in $marks) { if ($cl -like ('*' + $m + '*')) { $hit = $true } }; if (-not $hit) { break }; $top = [int]$par.ProcessId; $id = $top }; taskkill /PID $top /T /F | Out-Null; Start-Sleep -Milliseconds 500; if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { Write-Host ('port ' + $port + ': could not stop process ' + $id + ' - close its window by hand') } else { Write-Host ('port ' + $port + ': stopped') } }"

echo.
echo MongoDB keeps running as a Windows service.
timeout /t 5 >nul
exit /b 0
