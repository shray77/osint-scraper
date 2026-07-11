@echo off
REM ============================================================
REM  build_msi.bat — сборка MSI-пакета для OSINT Scraper
REM
REM  Требования:
REM    1. Python 3.10+ с установленными зависимостями
REM    2. PyInstaller:        pip install pyinstaller
REM    3. WiX Toolset v3.11+: https://wixtoolset.org/releases/
REM       (candle.exe и light.exe должны быть в PATH)
REM
REM  Запуск:
REM    packaging\build_msi.bat
REM
REM  Результат:
REM    packaging\OSINTScraper-1.1.0.msi
REM ============================================================

setlocal enabledelayedexpansion

set VERSION=1.1.0
set APPNAME=OSINTScraper
set SCRIPT_DIR=%~dp0..
set PACKAGING_DIR=%~dp0

cd /d "%SCRIPT_DIR%"

echo.
echo === [1/5] Очистка предыдущих сборок ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "%PACKAGING_DIR%\%APPNAME%-*.msi" del /q "%PACKAGING_DIR%\%APPNAME%-*.msi"
if exist "%PACKAGING_DIR%\%APPNAME%.wixobj" del /q "%PACKAGING_DIR%\%APPNAME%.wixobj"
if exist "%PACKAGING_DIR%\ProductComponents.wxs" del /q "%PACKAGING_DIR%\ProductComponents.wxs"

echo.
echo === [2/5] Сборка через PyInstaller ===
pyinstaller packaging\osint_scraper.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller failed
    exit /b 1
)

echo.
echo === [3/5] Harvest файлов через heat.exe ===
REM heat.exe собирает все файлы из dist/OSINTScraper в ComponentGroup
heat dir dist\%APPNAME% ^
    -cg ProductComponents ^
    -dr INSTALLDIR ^
    -ke -srd -sreg -gg -var var.SourceDir ^
    -out "%PACKAGING_DIR%\ProductComponents.wxs" ^
    -t "%PACKAGING_DIR%\heat-transform.xslt"

if errorlevel 1 (
    echo ERROR: heat.exe failed
    echo Убедитесь, что WiX Toolset установлен и в PATH
    exit /b 1
)

echo.
echo === [4/5] Компиляция WiX через candle.exe ===
candle "%PACKAGING_DIR%\osint_scraper.wxs" ^
       -out "%PACKAGING_DIR%\osint_scraper.wixobj" ^
       -dSourceDir="%SCRIPT_DIR%\dist\%APPNAME%" ^
       -ext WixUIExtension ^
       -ext WixUtilExtension

if errorlevel 1 (
    echo ERROR: candle.exe failed
    exit /b 1
)

REM Также компилируем ProductComponents
candle "%PACKAGING_DIR%\ProductComponents.wxs" ^
       -out "%PACKAGING_DIR%\ProductComponents.wixobj" ^
       -dSourceDir="%SCRIPT_DIR%\dist\%APPNAME%"

if errorlevel 1 (
    echo ERROR: candle.exe for ProductComponents failed
    exit /b 1
)

echo.
echo === [5/5] Линковка MSI через light.exe ===
light "%PACKAGING_DIR%\osint_scraper.wixobj" ^
      "%PACKAGING_DIR%\ProductComponents.wixobj" ^
      -out "%PACKAGING_DIR%\%APPNAME%-%VERSION%.msi" ^
      -ext WixUIExtension ^
      -ext WixUtilExtension ^
      -b "%SCRIPT_DIR%\dist\%APPNAME%"

if errorlevel 1 (
    echo ERROR: light.exe failed
    exit /b 1
)

echo.
echo ============================================================
echo  MSI готов: %PACKAGING_DIR%\%APPNAME%-%VERSION%.msi
echo ============================================================
echo.
echo  Установка:
echo    1. Двойной клик по .msi файлу
echo    2. Следуйте указаниям мастера
echo    3. После установки — Пуск ^> OSINT Scraper
echo.
echo  Размер:
for %%I in ("%PACKAGING_DIR%\%APPNAME%-%VERSION%.msi") do echo    %%~zI байт

endlocal
