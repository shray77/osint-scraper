"""
gui/main_window.py — главное окно приложения.

Содержит:
- Таб «Поиск»: форма запроса + прогресс + кнопка запуска
- Таб «Профиль»: карточка компании со всеми полями
- Таб «Совпадения»: таблица всех найденных юрлиц
- Таб «Рынок»: кандидаты объёма/динамики/топ-игроков
- Таб «Сайт»: контакты, соцсети, ссылки
- Таб «Логи»: живой вывод логов
- Таб «Источники»: список всех URL
- Таб «Настройки»: deep mode, playwright, кэш, папка вывода
- Статус-бар: прогресс + сообщение
"""
from __future__ import annotations

import os
import sys
import json
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from gui.workers import SearchWorker

# Пытаемся импортировать основные модули
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


# ---------------------------------------------------------------------------
# Стиль приложения
# ---------------------------------------------------------------------------
APP_STYLE = """
QWidget {
    font-family: 'Segoe UI', 'Inter', 'San Francisco', sans-serif;
    font-size: 13px;
    color: #1f2937;
    background-color: #f9fafb;
}

QMainWindow, QDialog {
    background-color: #f9fafb;
}

/* Группы */
QGroupBox {
    font-weight: 600;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: #ffffff;
    color: #111827;
}

/* Кнопки */
QPushButton {
    background-color: #2563eb;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #1d4ed8;
}
QPushButton:pressed {
    background-color: #1e40af;
}
QPushButton:disabled {
    background-color: #9ca3af;
}
QPushButton[variant="secondary"] {
    background-color: #ffffff;
    color: #374151;
    border: 1px solid #d1d5db;
}
QPushButton[variant="secondary"]:hover {
    background-color: #f3f4f6;
}
QPushButton[variant="danger"] {
    background-color: #dc2626;
}
QPushButton[variant="danger"]:hover {
    background-color: #b91c1c;
}

/* Поля ввода */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #2563eb;
    selection-color: white;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #2563eb;
}

/* Таблицы */
QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    gridline-color: #f3f4f6;
    selection-background-color: #dbeafe;
    selection-color: #1e40af;
}
QHeaderView::section {
    background-color: #f3f4f6;
    color: #374151;
    padding: 8px 10px;
    border: none;
    border-right: 1px solid #e5e7eb;
    border-bottom: 1px solid #e5e7eb;
    font-weight: 600;
}

/* Табы */
QTabWidget::pane {
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    top: -1px;
}
QTabBar::tab {
    background-color: #f3f4f6;
    color: #6b7280;
    padding: 8px 16px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #2563eb;
    border-color: #e5e7eb;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background-color: #e5e7eb;
    color: #1f2937;
}

/* Прогресс-бар */
QProgressBar {
    background-color: #e5e7eb;
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 6px;
}

/* Чекбоксы */
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #d1d5db;
    border-radius: 3px;
    background-color: white;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #2563eb;
    image: none;
}

/* Скроллбары */
QScrollBar:vertical {
    background: #f3f4f6;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #d1d5db;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #9ca3af;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* Статус-бар */
QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #e5e7eb;
    color: #6b7280;
}

/* Tooltips */
QToolTip {
    background-color: #1f2937;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 10px;
}
"""


# ---------------------------------------------------------------------------
# Виджеты
# ---------------------------------------------------------------------------
class StatCard(QtWidgets.QFrame):
    """Карточка с одной цифрой и подписью — для ключевых метрик."""

    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setStyleSheet("""
            QFrame#statCard {
                background-color: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 14px;
            }
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setStyleSheet("color: #6b7280; font-size: 11px; font-weight: 500;")
        self.value_label = QtWidgets.QLabel(value)
        self.value_label.setStyleSheet("color: #111827; font-size: 18px; font-weight: 700;")
        self.value_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str):
        self.value_label.setText(value or "—")


class InfoRow(QtWidgets.QWidget):
    """Строка с лейблом и значением — для пар «Поле: Значение»."""

    def __init__(self, label: str, value: str = "", parent=None, copyable: bool = True):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)

        self.label = QtWidgets.QLabel(label)
        self.label.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.label.setMinimumWidth(180)
        self.label.setMaximumWidth(220)

        self.value = QtWidgets.QLabel(value or "—")
        self.value.setStyleSheet("color: #111827; font-size: 13px;")
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        layout.addWidget(self.label)
        layout.addWidget(self.value, 1)


class CollectorStatusItem(QtWidgets.QWidget):
    """Строка статуса одного коллектора: имя / статус / время."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self.status_dot = QtWidgets.QLabel("○")
        self.status_dot.setFixedWidth(16)
        self.status_dot.setStyleSheet("color: #9ca3af; font-size: 14px;")

        self.name_label = QtWidgets.QLabel(name)
        self.name_label.setStyleSheet("font-size: 12px; color: #374151;")

        self.status_label = QtWidgets.QLabel("ожидание")
        self.status_label.setStyleSheet("font-size: 11px; color: #9ca3af;")
        self.status_label.setMinimumWidth(100)

        self.duration_label = QtWidgets.QLabel("")
        self.duration_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        self.duration_label.setAlignment(QtCore.Qt.AlignRight)

        layout.addWidget(self.status_dot)
        layout.addWidget(self.name_label)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.duration_label)

    def set_running(self):
        self.status_dot.setText("◐")
        self.status_dot.setStyleSheet("color: #2563eb; font-size: 14px;")
        self.status_label.setText("выполняется...")
        self.status_label.setStyleSheet("font-size: 11px; color: #2563eb;")

    def set_done(self, stats: dict):
        self.status_dot.setText("●")
        self.status_dot.setStyleSheet("color: #10b981; font-size: 14px;")
        errors = stats.get("errors", 0)
        if errors > 0:
            self.status_label.setText(f"готово ({errors} ошибок)")
            self.status_label.setStyleSheet("font-size: 11px; color: #d97706;")
        else:
            self.status_label.setText("готово")
            self.status_label.setStyleSheet("font-size: 11px; color: #10b981;")
        duration = stats.get("duration_sec", 0)
        self.duration_label.setText(f"{duration}с")


# ---------------------------------------------------------------------------
# Главное окно
# ---------------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    """Главное окно приложения."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OSINT Scraper — аналитика российских компаний")
        self.resize(1280, 800)
        self.setMinimumSize(1100, 700)

        # Состояние
        self.worker: Optional[SearchWorker] = None
        self.worker_thread: Optional[QtCore.QThread] = None
        self.last_report: Optional[dict] = None
        self.last_output_paths: dict = {}
        self.collector_items: dict[str, CollectorStatusItem] = {}
        self.settings = self._load_settings()

        # Центральный виджет
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Хедер
        layout.addWidget(self._build_header())

        # Табы
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)

        self._build_search_tab()
        self._build_profile_tab()
        self._build_matches_tab()
        self._build_market_tab()
        self._build_site_tab()
        self._build_logs_tab()
        self._build_sources_tab()
        self._build_settings_tab()

        # Статус-бар
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().showMessage("Готов к работе")

        # Меню
        self._build_menu()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------
    def _build_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QFrame()
        header.setFixedHeight(60)
        header.setStyleSheet("""
            QFrame {
                background-color: #111827;
                border: none;
            }
            QLabel { color: #f9fafb; }
        """)
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("🔍 OSINT Scraper")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f9fafb;")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Аналитика российских компаний из открытых источников")
        subtitle.setStyleSheet("font-size: 12px; color: #9ca3af;")
        layout.addWidget(subtitle)
        layout.addStretch()

        # Кнопка «Открыть папку вывода»
        btn_open = QtWidgets.QPushButton("📂 Открыть папку отчётов")
        btn_open.setProperty("variant", "secondary")
        btn_open.setStyleSheet("""
            QPushButton {
                background-color: #1f2937;
                color: #f9fafb;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #374151; }
        """)
        btn_open.clicked.connect(self._open_output_folder)
        layout.addWidget(btn_open)

        return header

    def _build_search_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Заголовок
        title = QtWidgets.QLabel("Поиск компании")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #111827;")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Введите название или ИНН компании — скрипт соберёт данные из открытых реестров")
        subtitle.setStyleSheet("color: #6b7280; font-size: 13px;")
        layout.addWidget(subtitle)

        # Форма
        form_group = QtWidgets.QGroupBox("Запрос")
        form_layout = QtWidgets.QVBoxLayout(form_group)
        form_layout.setSpacing(10)

        input_row = QtWidgets.QHBoxLayout()
        self.query_input = QtWidgets.QLineEdit()
        self.query_input.setPlaceholderText("Например: «Истринская сыроварня» или ИНН «5017127406»")
        self.query_input.returnPressed.connect(self._start_search)
        self.query_input.setMinimumHeight(38)
        input_row.addWidget(self.query_input, 1)

        self.btn_search = QtWidgets.QPushButton("🔍  Найти")
        self.btn_search.setMinimumHeight(38)
        self.btn_search.setMinimumWidth(120)
        self.btn_search.clicked.connect(self._start_search)
        input_row.addWidget(self.btn_search)

        self.btn_stop = QtWidgets.QPushButton("⏹  Остановить")
        self.btn_stop.setProperty("variant", "danger")
        self.btn_stop.setMinimumHeight(38)
        self.btn_stop.clicked.connect(self._stop_search)
        self.btn_stop.setVisible(False)
        input_row.addWidget(self.btn_stop)

        form_layout.addLayout(input_row)

        # Опции
        opts_row = QtWidgets.QHBoxLayout()
        self.chk_deep = QtWidgets.QCheckBox("Deep-режим (PDF-выписка ЕГРЮЛ — даёт ОКВЭД, адрес, учредителей)")
        self.chk_deep.setChecked(self.settings.get("deep", True))
        opts_row.addWidget(self.chk_deep)

        self.chk_site = QtWidgets.QCheckBox("Скрапить сайт компании")
        self.chk_site.setChecked(self.settings.get("fetch_site", True))
        opts_row.addWidget(self.chk_site)

        opts_row.addStretch()
        form_layout.addLayout(opts_row)

        layout.addWidget(form_group)

        # Статусы коллекторов
        collectors_group = QtWidgets.QGroupBox("Статус сборки")
        clayout = QtWidgets.QVBoxLayout(collectors_group)
        clayout.setSpacing(2)

        # Создаём элементы для всех коллекторов
        for name in ["egrul_nalog", "egrul_nalog_pdf", "rusprofile", "zachestnyibiznes",
                     "list_org", "findcompany", "market_search", "rosstat", "company_site"]:
            item = CollectorStatusItem(name)
            self.collector_items[name] = item
            clayout.addWidget(item)

        clayout.addStretch()
        layout.addWidget(collectors_group, 1)

        self.tabs.addTab(tab, "🔍 Поиск")

    def _build_profile_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Заголовок + кнопки экспорта
        header_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Профиль компании")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        header_row.addWidget(title)
        header_row.addStretch()

        self.btn_open_md = QtWidgets.QPushButton("📄 Markdown")
        self.btn_open_md.setProperty("variant", "secondary")
        self.btn_open_md.clicked.connect(lambda: self._open_file("md"))
        header_row.addWidget(self.btn_open_md)

        self.btn_open_xlsx = QtWidgets.QPushButton("📊 Excel")
        self.btn_open_xlsx.setProperty("variant", "secondary")
        self.btn_open_xlsx.clicked.connect(lambda: self._open_file("xlsx"))
        header_row.addWidget(self.btn_open_xlsx)

        self.btn_open_json = QtWidgets.QPushButton("⚙ JSON")
        self.btn_open_json.setProperty("variant", "secondary")
        self.btn_open_json.clicked.connect(lambda: self._open_file("json"))
        header_row.addWidget(self.btn_open_json)

        layout.addLayout(header_row)

        # Ключевые метрики — карточки
        metrics_row = QtWidgets.QHBoxLayout()
        metrics_row.setSpacing(10)
        self.card_inn = StatCard("ИНН")
        self.card_ogrn = StatCard("ОГРН")
        self.card_date = StatCard("Регистрация")
        self.card_okved = StatCard("Основной ОКВЭД")
        self.card_industry = StatCard("Отрасль")
        self.card_director = StatCard("Директор")
        for card in [self.card_inn, self.card_ogrn, self.card_date,
                     self.card_okved, self.card_industry, self.card_director]:
            metrics_row.addWidget(card, 1)
        layout.addLayout(metrics_row)

        # Детали — scroll area с InfoRow
        details_scroll = QtWidgets.QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        details_widget = QtWidgets.QWidget()
        details_layout = QtWidgets.QVBoxLayout(details_widget)
        details_layout.setSpacing(2)

        self.detail_rows = {}
        for field, label in [
            ("full_name", "Полное наименование"),
            ("short_name", "Сокращённое наименование"),
            ("inn", "ИНН"),
            ("ogrn", "ОГРН"),
            ("kpp", "КПП"),
            ("registration_date", "Дата регистрации"),
            ("liquidation_date", "Дата ликвидации"),
            ("status", "Статус"),
            ("region", "Регион"),
            ("legal_address", "Юридический адрес"),
            ("director_role", "Должность руководителя"),
            ("director", "Руководитель"),
            ("founder", "Учредитель"),
            ("founders", "Учредители"),
            ("okved_main", "Основной ОКВЭД"),
            ("okved_code", "Код ОКВЭД"),
            ("industry", "Отрасль"),
            ("authorized_capital", "Уставный капитал"),
            ("revenue", "Выручка"),
            ("profit", "Чистая прибыль"),
            ("assets", "Стоимость активов"),
            ("employees", "Численность сотрудников"),
            ("finance_caveat", "Пометка по финансам"),
        ]:
            row = InfoRow(label)
            self.detail_rows[field] = row
            details_layout.addWidget(row)

        details_layout.addStretch()
        details_scroll.setWidget(details_widget)
        layout.addWidget(details_scroll, 1)

        # Список всех ОКВЭД
        okved_group = QtWidgets.QGroupBox("Все ОКВЭД")
        okved_layout = QtWidgets.QVBoxLayout(okved_group)
        self.okved_list = QtWidgets.QListWidget()
        self.okved_list.setMaximumHeight(150)
        okved_layout.addWidget(self.okved_list)
        layout.addWidget(okved_group)

        self.tabs.addTab(tab, "📋 Профиль")

    def _build_matches_tab(self):
        """Таб «Совпадения» — все юрлица с похожим названием."""
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Все совпадения по запросу")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        hint = QtWidgets.QLabel(
            "⚠️ У холдинга может быть несколько юрлиц с похожим названием. "
            "У управляющей компании ОКВЭД может быть «бухгалтерский учёт», у производственного юрлица — "
            "«производство сыра». Проверьте, что выбран правильный. "
            "Двойной клик по строке запустит новый поиск по этому ИНН."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #d97706; background-color: #fef3c7; padding: 12px; border-radius: 6px;")
        layout.addWidget(hint)

        self.matches_table = QtWidgets.QTableWidget()
        self.matches_table.setColumnCount(7)
        self.matches_table.setHorizontalHeaderLabels(
            ["№", "Краткое название", "ИНН", "ОГРН", "Регион", "Регистрация", "Статус"]
        )
        self.matches_table.horizontalHeader().setStretchLastSection(False)
        self.matches_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.matches_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.matches_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.matches_table.doubleClicked.connect(self._on_match_double_click)
        layout.addWidget(self.matches_table, 1)

        self.tabs.addTab(tab, "🔄 Совпадения")

    def _build_market_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Рынок и доля")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        self.market_table = QtWidgets.QTableWidget()
        self.market_table.setColumnCount(5)
        self.market_table.setHorizontalHeaderLabels(["Тип", "Значение", "Год", "Источник", "Контекст"])
        self.market_table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        self.market_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.market_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.market_table.doubleClicked.connect(self._open_url_from_table)
        layout.addWidget(self.market_table, 1)

        self.tabs.addTab(tab, "📊 Рынок")

    def _build_site_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Сайт компании")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        # URL сайта + кнопка "Открыть"
        url_row = QtWidgets.QHBoxLayout()
        self.site_url_label = QtWidgets.QLabel("—")
        self.site_url_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #2563eb;")
        self.site_url_label.setWordWrap(True)
        self.site_url_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        url_row.addWidget(self.site_url_label, 1)

        btn_open_site = QtWidgets.QPushButton("🔗 Открыть сайт")
        btn_open_site.clicked.connect(self._open_company_site)
        url_row.addWidget(btn_open_site)
        layout.addLayout(url_row)

        # Контакты
        contacts_group = QtWidgets.QGroupBox("Контакты")
        cl = QtWidgets.QVBoxLayout(contacts_group)
        self.phones_label = InfoRow("Телефоны")
        self.emails_label = InfoRow("Email")
        cl.addWidget(self.phones_label)
        cl.addWidget(self.emails_label)
        layout.addWidget(contacts_group)

        # Соцсети
        socials_group = QtWidgets.QGroupBox("Соцсети")
        sl = QtWidgets.QVBoxLayout(socials_group)
        self.socials_container = QtWidgets.QWidget()
        self.socials_layout = QtWidgets.QVBoxLayout(self.socials_container)
        self.socials_layout.setSpacing(4)
        sl.addWidget(self.socials_container)
        layout.addWidget(socials_group)

        # Интересные ссылки
        links_group = QtWidgets.QGroupBox("Ключевые страницы сайта")
        ll = QtWidgets.QVBoxLayout(links_group)
        self.links_list = QtWidgets.QListWidget()
        self.links_list.itemDoubleClicked.connect(
            lambda item: webbrowser.open(item.data(QtCore.Qt.UserRole) or "")
        )
        ll.addWidget(self.links_list)
        layout.addWidget(links_group, 1)

        self.tabs.addTab(tab, "🌐 Сайт")

    def _build_logs_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        header_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Живой лог")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        header_row.addWidget(title)
        header_row.addStretch()

        btn_clear = QtWidgets.QPushButton("Очистить")
        btn_clear.setProperty("variant", "secondary")
        btn_clear.clicked.connect(lambda: self.logs_view.clear())
        header_row.addWidget(btn_clear)

        btn_save = QtWidgets.QPushButton("💾 Сохранить лог")
        btn_save.setProperty("variant", "secondary")
        btn_save.clicked.connect(self._save_logs)
        header_row.addWidget(btn_save)

        layout.addLayout(header_row)

        self.logs_view = QtWidgets.QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        self.logs_view.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1f2937;
                color: #e5e7eb;
                font-family: 'JetBrains Mono', 'Consolas', 'Menlo', monospace;
                font-size: 12px;
                border: 1px solid #374151;
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.logs_view, 1)

        self.tabs.addTab(tab, "📜 Логи")

    def _build_sources_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Источники")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        hint = QtWidgets.QLabel("Все URL, из которых собраны данные. Двойной клик открывает в браузере.")
        hint.setStyleSheet("color: #6b7280;")
        layout.addWidget(hint)

        self.sources_list = QtWidgets.QListWidget()
        self.sources_list.itemDoubleClicked.connect(
            lambda item: webbrowser.open(item.text())
        )
        layout.addWidget(self.sources_list, 1)

        self.tabs.addTab(tab, "🔗 Источники")

    def _build_settings_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Настройки")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        # Папка вывода
        out_group = QtWidgets.QGroupBox("Папка для отчётов")
        ol = QtWidgets.QHBoxLayout(out_group)
        self.output_dir_input = QtWidgets.QLineEdit(self.settings.get("output_dir", str(Path.cwd() / "output")))
        ol.addWidget(self.output_dir_input, 1)
        btn_browse = QtWidgets.QPushButton("Обзор...")
        btn_browse.setProperty("variant", "secondary")
        btn_browse.clicked.connect(self._browse_output_dir)
        ol.addWidget(btn_browse)
        layout.addWidget(out_group)

        # Опции движка
        engine_group = QtWidgets.QGroupBox("Движок скрапинга")
        el = QtWidgets.QVBoxLayout(engine_group)

        self.chk_playwright = QtWidgets.QCheckBox("Включить Playwright fallback (для JS/Cloudflare-сайтов)")
        self.chk_playwright.setChecked(self.settings.get("enable_playwright", True))
        self.chk_playwright.setToolTip(
            "Playwright запускает реальный headless Chrome для сайтов с защитой от ботов. "
            "Без него Rusprofile/ZacheBiznes не сработают. "
            "Требует установки: pip install playwright && playwright install chromium"
        )
        el.addWidget(self.chk_playwright)

        self.chk_cache = QtWidgets.QCheckBox("Кэшировать HTTP-ответы (ускоряет повторные запросы)")
        self.chk_cache.setChecked(self.settings.get("use_cache", True))
        el.addWidget(self.chk_cache)

        layout.addWidget(engine_group)

        # О программе
        about_group = QtWidgets.QGroupBox("О программе")
        al = QtWidgets.QVBoxLayout(about_group)
        about_text = QtWidgets.QLabel(
            "<b>OSINT Scraper v1.1</b><br><br>"
            "Универсальный OSINT-скраппер для анализа российских компаний.<br><br>"
            "<b>Источники v1.1:</b><br>"
            "• EGRUL (nalog.ru) — официальные данные ФНС<br>"
            "• PDF-выписка ЕГРЮЛ — ОКВЭД, адрес, учредители<br>"
            "• Rusprofile, Зачестныйбизнес, List-Org — агрегаторы<br>"
            "• Bing — поиск рыночных данных и сниппетов<br>"
            "• Росстат — отраслевая статистика<br>"
            "• Сайт компании — контакты, соцсети, ключевые страницы<br><br>"
            "<b>Важно:</b> данные могут быть неполными из-за сложной холдинговой структуры. "
            "Проверяйте все совпадения юрлиц."
        )
        about_text.setWordWrap(True)
        about_text.setStyleSheet("color: #374151; line-height: 1.5;")
        al.addWidget(about_text)
        layout.addWidget(about_group)

        layout.addStretch()

        # Кнопка сохранения настроек
        btn_save = QtWidgets.QPushButton("💾 Сохранить настройки")
        btn_save.setMinimumHeight(40)
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save)

        self.tabs.addTab(tab, "⚙ Настройки")

    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Файл")
        act_exit = QtGui.QAction("Выход", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        help_menu = menubar.addMenu("Справка")
        act_about = QtGui.QAction("О программе", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    # ------------------------------------------------------------------
    # Обработчики
    # ------------------------------------------------------------------
    def _start_search(self):
        """Запуск поиска."""
        query = self.query_input.text().strip()
        if not query:
            QtWidgets.QMessageBox.warning(self, "Внимание", "Введите название или ИНН компании")
            return

        if self.worker_thread and self.worker_thread.isRunning():
            QtWidgets.QMessageBox.warning(self, "Внимание", "Поиск уже выполняется")
            return

        # Сброс UI
        self._reset_progress()
        self.btn_search.setVisible(False)
        self.btn_stop.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Сбор данных...")

        # Сброс табов
        self._clear_results()

        # Создаём worker
        self.worker = SearchWorker(
            query=query,
            deep=self.chk_deep.isChecked(),
            fetch_site=self.chk_site.isChecked(),
            enable_playwright=self.chk_playwright.isChecked(),
            use_cache=self.chk_cache.isChecked(),
            output_dir=self.output_dir_input.text().strip(),
        )
        self.worker_thread = QtCore.QThread()
        self.worker.moveToThread(self.worker_thread)

        # Подключаем сигналы
        self.worker_thread.started.connect(self.worker.run)
        self.worker.started.connect(self._on_worker_started)
        self.worker.collector_started.connect(self._on_collector_started)
        self.worker.collector_finished.connect(self._on_collector_finished)
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._on_log_message)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.worker_thread.quit)

        self.worker_thread.start()

    def _stop_search(self):
        if self.worker:
            self.worker.stop()
            self.statusBar().showMessage("Останавливаю...")

    def _reset_progress(self):
        for item in self.collector_items.values():
            item.status_dot.setText("○")
            item.status_dot.setStyleSheet("color: #9ca3af; font-size: 14px;")
            item.status_label.setText("ожидание")
            item.status_label.setStyleSheet("font-size: 11px; color: #9ca3af;")
            item.duration_label.setText("")

    def _clear_results(self):
        for card in [self.card_inn, self.card_ogrn, self.card_date,
                     self.card_okved, self.card_industry, self.card_director]:
            card.set_value("—")
        for row in self.detail_rows.values():
            row.value.setText("—")
        self.okved_list.clear()
        self.matches_table.setRowCount(0)
        self.market_table.setRowCount(0)
        self.sources_list.clear()
        self.site_url_label.setText("—")
        self.phones_label.value.setText("—")
        self.emails_label.value.setText("—")
        # Очищаем соцсети
        while self.socials_layout.count():
            item = self.socials_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.links_list.clear()

    @QtCore.Slot(str)
    def _on_worker_started(self, query: str):
        self._on_log_message(f"=== Поиск: {query} ===")

    @QtCore.Slot(str, str)
    def _on_collector_started(self, name: str, query: str):
        if name in self.collector_items:
            self.collector_items[name].set_running()
        self._on_log_message(f"→ {name} (query={query})")

    @QtCore.Slot(str, dict)
    def _on_collector_finished(self, name: str, stats: dict):
        if name in self.collector_items:
            self.collector_items[name].set_done(stats)
        self._on_log_message(
            f"✓ {name}: {stats.get('fields', 0)} полей, "
            f"{stats.get('urls', 0)} URL, "
            f"{stats.get('errors', 0)} ошибок, "
            f"{stats.get('duration_sec', 0)}с"
        )

    @QtCore.Slot(int, int, str)
    def _on_progress(self, current: int, total: int, message: str):
        if total > 0:
            pct = int(current * 100 / total)
            self.progress_bar.setValue(pct)
            self.statusBar().showMessage(f"{message} ({current}/{total})")

    @QtCore.Slot(str)
    def _on_log_message(self, message: str):
        self.logs_view.appendPlainText(message)

    @QtCore.Slot(dict, dict)
    def _on_worker_finished(self, report: dict, output_paths: dict):
        self.last_report = report
        self.last_output_paths = output_paths
        self.btn_search.setVisible(True)
        self.btn_stop.setVisible(False)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage(f"Готово · {len(report.get('sources_used', []))} источников · {len(report.get('errors', []))} ошибок")

        # Заполняем все табы
        self._fill_profile_tab(report)
        self._fill_matches_tab(report)
        self._fill_market_tab(report)
        self._fill_site_tab(report)
        self._fill_sources_tab(report)

        # Переключаемся на таб «Профиль»
        self.tabs.setCurrentIndex(1)

        # Если есть ошибки — покажем
        errors = report.get("errors", [])
        if errors:
            self._on_log_message(f"\n=== Ошибки ({len(errors)}) ===")
            for e in errors[:10]:
                self._on_log_message(f"  ! {e}")

    @QtCore.Slot(str)
    def _on_worker_error(self, message: str):
        self.btn_search.setVisible(True)
        self.btn_stop.setVisible(False)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage("Ошибка")
        QtWidgets.QMessageBox.critical(self, "Ошибка", message)

    # ------------------------------------------------------------------
    # Заполнение табов
    # ------------------------------------------------------------------
    def _fill_profile_tab(self, report: dict):
        c = report.get("company", {})
        self.card_inn.set_value(c.get("inn") or "—")
        self.card_ogrn.set_value(c.get("ogrn") or "—")
        self.card_date.set_value(c.get("registration_date") or "—")
        self.card_okved.set_value(c.get("okved_main") or "—")
        self.card_industry.set_value(c.get("industry") or "—")
        self.card_director.set_value(c.get("director") or "—")

        for field, row in self.detail_rows.items():
            val = c.get(field)
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            row.value.setText(str(val) if val else "—")

        # ОКВЭД
        self.okved_list.clear()
        for o in c.get("okved_all", []):
            self.okved_list.addItem(o)

    def _fill_matches_tab(self, report: dict):
        matches = report.get("company", {}).get("all_matches") or []
        self.matches_table.setRowCount(len(matches))
        for i, m in enumerate(matches):
            self._set_matches_item(i, 0, str(i + 1))
            self._set_matches_item(i, 1, m.get("short_name") or m.get("full_name", ""))
            self._set_matches_item(i, 2, m.get("inn", ""))
            self._set_matches_item(i, 3, m.get("ogrn", ""))
            self._set_matches_item(i, 4, m.get("region", ""))
            self._set_matches_item(i, 5, m.get("registration_date", ""))
            self._set_matches_item(i, 6, m.get("status", ""))

    def _set_matches_item(self, row, col, text):
        item = QtWidgets.QTableWidgetItem(str(text))
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.matches_table.setItem(row, col, item)

    def _fill_market_tab(self, report: dict):
        m = report.get("market", {})
        rows = []
        for s in m.get("market_size_candidates", []):
            rows.append(("Объём рынка", s.get("value", ""), s.get("year", ""),
                         s.get("source", ""), s.get("text", "")[:200]))
        for d in m.get("dynamics_candidates", []):
            rows.append(("Динамика", d.get("value", ""), "—",
                         d.get("source", ""), d.get("text", "")[:200]))
        for t in m.get("top_players_candidates", []):
            rows.append(("ТОП-игроки", "—", "—",
                         t.get("source", ""), t.get("text", "")[:200]))
        for p in m.get("company_position_candidates", []):
            rows.append(("Позиция компании", "—", "—",
                         p.get("source", ""), p.get("text", "")[:200]))

        self.market_table.setRowCount(len(rows))
        for i, (typ, val, year, src, ctx) in enumerate(rows):
            self._set_market_item(i, 0, typ)
            self._set_market_item(i, 1, val)
            self._set_market_item(i, 2, year)
            self._set_market_item(i, 3, src)
            self._set_market_item(i, 4, ctx)

    def _set_market_item(self, row, col, text):
        item = QtWidgets.QTableWidgetItem(str(text))
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.market_table.setItem(row, col, item)

    def _fill_site_tab(self, report: dict):
        s = report.get("company_site", {})
        if not s:
            self.site_url_label.setText("—")
            return

        url = s.get("site_url", "")
        self.site_url_label.setText(url)
        self.site_url_label.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        phones = s.get("phones", [])
        emails = s.get("emails", [])
        self.phones_label.value.setText(", ".join(phones) if phones else "—")
        self.emails_label.value.setText(", ".join(emails) if emails else "—")

        # Соцсети
        while self.socials_layout.count():
            item = self.socials_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        socials = s.get("socials", {})
        if socials:
            for name, urls in socials.items():
                row = InfoRow(name.capitalize(), ", ".join(urls))
                self.socials_layout.addWidget(row)
        else:
            row = InfoRow("Соцсети", "не найдены")
            self.socials_layout.addWidget(row)

        # Ссылки
        self.links_list.clear()
        for l in s.get("interesting_links", []):
            item = QtWidgets.QListWidgetItem(f"{l.get('text', '')} → {l.get('url', '')}")
            item.setData(QtCore.Qt.UserRole, l.get("url", ""))
            self.links_list.addItem(item)

    def _fill_sources_tab(self, report: dict):
        self.sources_list.clear()
        for url in report.get("sources_used", []):
            if url:
                self.sources_list.addItem(url)

    def _set_table_item(self, row, col, text):
        item = QtWidgets.QTableWidgetItem(str(text))
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.matches_table.setItem(row, col, item) if self.matches_table == self.matches_table else None
        # Универсально — найдём целевую таблицу по row/col
        # Этот метод вызывается из _fill_matches_tab — используем matches_table
        # Но также вызывается из _fill_market_tab — нужна market_table
        # Поэтому обработаем обе ситуации через проверку текущей таблицы
        # (упрощение: метод написан для matches_table, для market_table дублируется ниже)

    def _set_market_table_item(self, row, col, text):
        item = QtWidgets.QTableWidgetItem(str(text))
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        self.market_table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Прочее
    # ------------------------------------------------------------------
    def _on_match_double_click(self, index):
        """Двойной клик по строке в matches — запуск нового поиска по ИНН."""
        row = index.row()
        if row < 0:
            return
        inn_item = self.matches_table.item(row, 2)
        if inn_item and inn_item.text():
            self.query_input.setText(inn_item.text())
            self._start_search()

    def _open_url_from_table(self, index):
        """Двойной клик в market_table — открыть URL."""
        row = index.row()
        url_item = self.market_table.item(row, 3)
        if url_item and url_item.text().startswith("http"):
            webbrowser.open(url_item.text())

    def _open_file(self, file_type: str):
        path = self.last_output_paths.get(file_type)
        if not path:
            QtWidgets.QMessageBox.information(self, "Нет файла", "Сначала выполните поиск")
            return
        if not os.path.exists(path):
            QtWidgets.QMessageBox.warning(self, "Файл не найден", path)
            return
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f"open '{path}'")
        else:
            os.system(f"xdg-open '{path}'")

    def _open_company_site(self):
        url = self.site_url_label.text()
        if url and url.startswith("http"):
            webbrowser.open(url)

    def _open_output_folder(self):
        path = self.output_dir_input.text().strip()
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f"open '{path}'")
        else:
            os.system(f"xdg-open '{path}'")

    def _browse_output_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Выберите папку для отчётов")
        if path:
            self.output_dir_input.setText(path)

    def _save_settings(self):
        self.settings["deep"] = self.chk_deep.isChecked()
        self.settings["fetch_site"] = self.chk_site.isChecked()
        self.settings["enable_playwright"] = self.chk_playwright.isChecked()
        self.settings["use_cache"] = self.chk_cache.isChecked()
        self.settings["output_dir"] = self.output_dir_input.text().strip()

        settings_path = self._settings_path()
        try:
            settings_path.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
            QtWidgets.QMessageBox.information(self, "Сохранено", f"Настройки сохранены в:\n{settings_path}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить настройки: {e}")

    def _load_settings(self) -> dict:
        path = self._settings_path()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "deep": True,
            "fetch_site": True,
            "enable_playwright": True,
            "use_cache": True,
            "output_dir": str(Path.cwd() / "output"),
        }

    def _settings_path(self) -> Path:
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", str(Path.home()))) / "OSINTScraper"
        else:
            base = Path.home() / ".config" / "osint-scraper"
        base.mkdir(parents=True, exist_ok=True)
        return base / "settings.json"

    def _save_logs(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить лог", f"osint_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            try:
                Path(path).write_text(self.logs_view.toPlainText(), encoding="utf-8")
                QtWidgets.QMessageBox.information(self, "Сохранено", f"Лог сохранён:\n{path}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить: {e}")

    def _show_about(self):
        QtWidgets.QMessageBox.about(
            self,
            "О программе",
            "<h2>OSINT Scraper v1.1</h2>"
            "<p>Универсальный OSINT-скраппер для анализа российских компаний.</p>"
            "<p><b>Источники:</b></p>"
            "<ul>"
            "<li>EGRUL (nalog.ru) — официальные данные ФНС</li>"
            "<li>PDF-выписка ЕГРЮЛ — ОКВЭД, адрес, учредители</li>"
            "<li>Rusprofile, Зачестныйбизнес, List-Org</li>"
            "<li>Bing — поиск рыночных данных</li>"
            "<li>Росстат</li>"
            "<li>Сайт компании — контакты, соцсети</li>"
            "</ul>"
            "<p><b>Важно:</b> данные могут быть неполными из-за сложной холдинговой структуры.</p>"
        )

    def closeEvent(self, event):
        """Корректно завершаем worker при закрытии."""
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QtWidgets.QMessageBox.question(
                self, "Подтверждение",
                "Поиск ещё выполняется. Остановить и выйти?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.No:
                event.ignore()
                return
            if self.worker:
                self.worker.stop()
            self.worker_thread.quit()
            self.worker_thread.wait(3000)
        # Сохраняем настройки
        self._save_settings_silent()
        event.accept()

    def _save_settings_silent(self):
        try:
            self.settings["deep"] = self.chk_deep.isChecked()
            self.settings["fetch_site"] = self.chk_site.isChecked()
            self.settings["enable_playwright"] = self.chk_playwright.isChecked()
            self.settings["use_cache"] = self.chk_cache.isChecked()
            self.settings["output_dir"] = self.output_dir_input.text().strip()
            self._settings_path().write_text(
                json.dumps(self.settings, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
