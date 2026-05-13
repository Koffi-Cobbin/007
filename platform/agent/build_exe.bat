@echo off
REM ============================================================================
REM Build dtask-agent as a standalone Windows executable via PyInstaller.
REM
REM Usage:
REM   build_exe.bat                   -- default (folder build)
REM   build_exe.bat --onefile         -- single dtask-agent.exe
REM   build_exe.bat --debug           -- verbose build with console
REM
REM The output goes to dist\dtask-agent\  (or dist\dtask-agent.exe for --onefile)
REM
REM Requirements:
REM   pip install pyinstaller
REM ============================================================================

setlocal enabledelayedexpansion
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%
set DIST_DIR=%PROJECT_DIR%dist

set FLAGS=--noconfirm --clean --log-level INFO
set NAME=dtask-agent

REM Parse arguments
:parse
if "%~1"=="--onefile" set FLAGS=%FLAGS% --onefile & shift & goto :parse
if "%~1"=="--debug" set FLAGS=%FLAGS% --log-level DEBUG --console & shift & goto :parse
if "%~1"=="--name" set NAME=%~2 & shift & shift & goto :parse

echo ============================================================================
echo  Building %NAME% with PyInstaller
echo  Project: %PROJECT_DIR%
echo  Flags:   %FLAGS%
echo ============================================================================

cd /d "%PROJECT_DIR%"

REM Check prerequisites
where pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PyInstaller not found. Install it with: pip install pyinstaller
    exit /b 1
)

REM Build
pyinstaller %FLAGS% ^
    --name "%NAME%" ^
    --add-data "config\agent.yaml;config" ^
    --hidden-import executor.handlers ^
    --hidden-import executor.handlers.checksum ^
    --hidden-import executor.handlers.file_processing ^
    --hidden-import executor.handlers.image_processing ^
    --hidden-import executor.handlers.data_transform ^
    --hidden-import executor.handlers.python_execution ^
    --hidden-import executor.handlers.numerical ^
    --hidden-import executor.plugin_base ^
    --hidden-import executor.loader ^
    --hidden-import executor.runner ^
    --hidden-import agent_core.service ^
    --collect-submodules executor ^
    --collect-submodules agent_core ^
    main.py

if %ERRORLEVEL% equ 0 (
    echo ============================================================================
    echo  BUILD SUCCESSFUL
    echo  Output: %DIST_DIR%\%NAME%\
    echo ============================================================================
    
    REM Copy the agent.yaml config alongside the exe for convenience
    if exist "%DIST_DIR%\%NAME%\config" (
        copy /Y "config\agent.yaml" "%DIST_DIR%\%NAME%\config\agent.yaml" >nul
        echo  Config: %DIST_DIR%\%NAME%\config\agent.yaml
    )
    echo.
    echo  To install as Windows service:
    echo    %DIST_DIR%\%NAME%\%NAME%.exe --install-service --master-url URL --enrollment-key KEY
    echo.
    echo  To run interactively:
    echo    %DIST_DIR%\%NAME%\%NAME%.exe --master-url URL --enrollment-key KEY
) else (
    echo ============================================================================
    echo  BUILD FAILED
    echo ============================================================================
    exit /b 1
)
