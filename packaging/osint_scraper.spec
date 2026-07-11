# PyInstaller spec для OSINT Scraper
#
# Сборка standalone exe:
#   pyinstaller packaging/osint_scraper.spec
#   или (из корня проекта):
#   pyinstaller osint_scraper.spec
#
# Результат: dist/OSINTScraper/OSINTScraper.exe (.exe на Windows)
#
# Для MSI: потом запустить WiX (см. packaging/build_msi.bat)

# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Определяем корень проекта: spec лежит в packaging/, поэтому корень — на 1 уровень выше
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC)) if 'SPEC' in dir() else os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SPEC_DIR) if os.path.basename(SPEC_DIR) == 'packaging' else SPEC_DIR

block_cipher = None

# Собираем все данные и подмодули PySide6
pyside_datas = collect_data_files('PySide6')
pyside_hidden = collect_submodules('PySide6')

# Ресурсы приложения (иконки)
datas = [
    (os.path.join(PROJECT_ROOT, 'gui/resources'), 'gui/resources'),
    (os.path.join(PROJECT_ROOT, 'README.md'), '.'),
    (os.path.join(PROJECT_ROOT, '__version__.py'), '.'),
    (os.path.join(PROJECT_ROOT, 'packaging/OSINTScraper-debug.bat'), '.'),
]

# certifi сертификаты — критично для Windows (без этого SSL не работает)
try:
    import certifi
    datas.append((os.path.dirname(certifi.__file__), 'certifi'))
except Exception:
    pass

# Hidden imports
hiddenimports = [
    'lxml',
    'lxml.etree',
    'bs4',
    'bs4.dammit',
    'requests',
    'urllib3',
    'certifi',
    'charset_normalizer',
    'openpyxl',
] + pyside_hidden

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'osint_app.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas + pyside_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'tkinter',
        'PyQt5',
        'PyQt6',
        # Playwright тяжёлый (128 МБ Chromium). Без него Rusprofile/Zache не сработают,
        # но основной пайплайн (EGRUL + ListOrg + Bing + Росстат + сайт) работает.
        # Если нужен Playwright — установите его отдельно: pip install playwright && playwright install chromium
        'playwright',
        'playwright._impl',
        'playwright.sync_api',
        'playwright.async_api',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OSINTScraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # v1.4.3: консоль выключена (убрали CMD окно)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, 'gui/resources/icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OSINTScraper',
)
