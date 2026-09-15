: << 'CMDBLOCK'
@echo off
REM Polyglot wrapper. On Windows, cmd.exe runs this batch half and calls Python directly.
REM On Unix, the shell skips the batch half (heredoc) and runs the script below.
REM Fail-open: every path exits 0 so the agent's tool call proceeds.
set "HOOK_DIR=%~dp0"
set "PYTHONPATH=%HOOK_DIR%..\src;%PYTHONPATH%"
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 -m readset.cli hook %*
    exit /b 0
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python -m readset.cli hook %*
    exit /b 0
)
exit /b 0
CMDBLOCK
exec "$(dirname "$0")/readset-hook" "$@"
