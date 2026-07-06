@echo off
REM ============================================================================
REM  run_daily_backfill.bat — unattended daily backfill wrapper
REM  Invoked by Windows Task Scheduler. Do NOT add interactive prompts here.
REM
REM  What it does:
REM    1. cd into the dbt project root (so `uv` finds .venv / pyproject)
REM    2. run full_auto_backfill.py --auto-run  (runs until today, no prompt,
REM       safe no-op if already up to date)
REM    3. append all output to a timestamped log under scripts\logs\
REM
REM  Reliability notes:
REM    * Full path to uv.exe — Task Scheduler runs with a minimal PATH.
REM    * Robust date via PowerShell — %DATE% formatting is locale-dependent.
REM    * Exit code of the python run is propagated so Task Scheduler "Last Run
REM      Result" reflects real success/failure.
REM ============================================================================

setlocal

REM --- paths -------------------------------------------------------------------
REM Derive the project root from THIS .bat's own location (it lives in scripts\),
REM so the file is portable and carries no personal path. %~dp0 ends in a
REM backslash, so %~dp0.. is the project root and %~dp0logs is scripts\logs.
REM Override UV_EXE if uv is installed elsewhere (a full path is used because Task
REM Scheduler runs with a minimal PATH that may not include uv).
set "UV_EXE=C:\Tools\uv\uv.exe"
set "PROJECT_ROOT=%~dp0.."
set "LOG_DIR=%~dp0logs"

REM --- force UTF-8 for ALL child python processes ------------------------------
REM Under Task Scheduler stdout is redirected to a file with the cp1252 code page,
REM so any non-Latin output (banner box chars, Hebrew) crashes with
REM UnicodeEncodeError. PYTHONUTF8=1 puts Python in UTF-8 mode and PROPAGATES to
REM every child process (02_extract_load, dbt via uv), making all output safe.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM --- timestamp (yyyy-MM-dd) for the log filename ----------------------------
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TODAY=%%i"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\auto_run_%TODAY%.log"

REM --- run ---------------------------------------------------------------------
cd /d "%PROJECT_ROOT%" || (echo Could not cd to project root & exit /b 1)

echo. >> "%LOG_FILE%"
echo ===== run_daily_backfill start %DATE% %TIME% ===== >> "%LOG_FILE%"
"%UV_EXE%" run python scripts\full_auto_backfill.py --auto-run >> "%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"
echo ===== run_daily_backfill end   %DATE% %TIME%  (exit=%RC%) ===== >> "%LOG_FILE%"

endlocal & exit /b %RC%
