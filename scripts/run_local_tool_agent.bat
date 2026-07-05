@echo off
setlocal

if "%~1"=="" (
  echo Usage: %~nx0 ^<server-url^> [agent-name] 1>&2
  exit /b 2
)

set "SCRIPT_DIR=%~dp0"
set "PYTHON_BIN=%PYTHON%"
if "%PYTHON_BIN%"=="" set "PYTHON_BIN=python"
set "AGENT_NAME=%~2"
if "%AGENT_NAME%"=="" set "AGENT_NAME=local-agent"

"%PYTHON_BIN%" "%SCRIPT_DIR%local_tool_agent.py" --server "%~1" --agent-name "%AGENT_NAME%"
exit /b %ERRORLEVEL%
