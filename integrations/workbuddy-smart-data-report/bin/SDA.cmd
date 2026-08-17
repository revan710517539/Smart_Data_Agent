@echo off
setlocal EnableExtensions

if defined SMART_DATA_AGENT_REPORT_CLI (
  "%SMART_DATA_AGENT_REPORT_CLI%" %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "%~dp0sda_report.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python "%~dp0sda_report.py" %*
  exit /b %ERRORLEVEL%
)

echo SDA: Python 3 is required to publish a report. 1>&2
exit /b 127
