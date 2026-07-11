@echo off
REM ============================================================
REM  OSINTScraper-debug.bat — запуск с pause для просмотра ошибок
REM
REM  Если основной OSINTScraper.exe вылетает, запусти этот .bat —
REM  окно консоли останется открытым, и ты увидишь traceback.
REM ============================================================

cd /d "%~dp0"

echo.
echo === OSINT Scraper debug mode ===
echo Crash log will be at:
echo   %%LOCALAPPDATA%%\OSINTScraper\logs\crash.log
echo.

OSINTScraper.exe

echo.
echo === Application exited with code: %ERRORLEVEL% ===
echo.
echo Crash log:
type "%LOCALAPPDATA%\OSINTScraper\logs\crash.log" 2>nul
echo.
pause
