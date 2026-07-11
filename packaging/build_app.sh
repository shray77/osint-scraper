#!/bin/bash
# ============================================================
#  build_app.sh — сборка standalone приложения OSINT Scraper
#
#  Запуск:
#    ./packaging/build_app.sh
#
#  Результат:
#    dist/OSINTScraper/ — папка с исполняемым файлом
#
#  На Linux: dist/OSINTScraper/OSINTScraper (ELF executable)
#  На Windows: dist/OSINTScraper/OSINTScraper.exe
#  На macOS: dist/OSINTScraper/OSINTScraper (Mach-O executable)
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

VERSION="1.1.0"
APPNAME="OSINTScraper"

echo ""
echo "=== [1/3] Очистка предыдущих сборок ==="
rm -rf build dist
rm -f packaging/*.msi packaging/*.wixobj packaging/ProductComponents.wxs
rm -f packaging/*-Setup-*.exe

echo ""
echo "=== [2/3] Проверка зависимостей ==="

if ! command -v python &> /dev/null; then
    echo "ERROR: python не установлен"
    exit 1
fi

if ! python -c "import PySide6" &> /dev/null; then
    echo "ERROR: PySide6 не установлен"
    echo "  Установите: pip install PySide6"
    exit 1
fi

if ! python -c "import PyInstaller" &> /dev/null; then
    echo "ERROR: PyInstaller не установлен"
    echo "  Установите: pip install pyinstaller"
    exit 1
fi

echo "  ✓ Python:     $(python --version 2>&1)"
echo "  ✓ PySide6:    $(python -c 'import PySide6; print(PySide6.__version__)' 2>&1)"
echo "  ✓ PyInstaller: $(python -c 'import PyInstaller; print(PyInstaller.__version__)' 2>&1)"

echo ""
echo "=== [3/3] Сборка через PyInstaller ==="
pyinstaller packaging/osint_scraper.spec --noconfirm

echo ""
echo "============================================================"
echo "  Сборка завершена"
echo "============================================================"
echo ""
echo "  Папка:  dist/$APPNAME/"
echo "  Файл:   dist/$APPNAME/$APPNAME$(if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then echo ".exe"; fi)"
echo ""
echo "  Размер:"
du -sh "dist/$APPNAME" 2>/dev/null || echo "    (не удалось определить)"
echo ""

# Подсказка по следующим шагам
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    echo "  Для создания MSI установщика:"
    echo "    packaging\\build_msi.bat"
    echo ""
    echo "  Для создания EXE установщика (Inno Setup):"
    echo "    iscc packaging\\installer.iss"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    echo "  Для создания .app пакета:"
    echo "    cp -r dist/$APPNAME dist/${APPNAME}.app"
    echo ""
    echo "  Для создания .dmg образа:"
    echo "    hdiutil create -volname \"$APPNAME $VERSION\" -srcfolder dist/${APPNAME}.app -ov -format UDZO dist/${APPNAME}-${VERSION}.dmg"
else
    echo "  Для создания .deb пакета:"
    echo "    (нужен дополнительный скрипт, см. README)"
    echo ""
    echo "  Для создания AppImage:"
    echo "    (нужен appimagetool, см. https://appimage.org/)"
fi
echo ""
